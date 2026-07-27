import { computed, ComputedRef } from 'vue'
import type {
  ExecutionNode,
  NodeEdge,
  NodeStatus,
  RunEvent,
  PlanTask,
  ToolCallGroup,
  ToolCall,
  IntermediateStep,
  TaskError,
} from '../types'

// ==================== 工具调用分组 ====================

function groupToolCalls(rawCalls: ToolCall[]): ToolCallGroup[] {
  const groups: ToolCallGroup[] = []
  for (const call of rawCalls) {
    const last = groups[groups.length - 1]
    if (last && last.toolName === call.toolName) {
      last.calls.push(call)
      last.count++
      last.key = `${call.toolName}-group-${last.calls[0].id}`
    } else {
      groups.push({
        key: `${call.toolName}-group-${call.id}`,
        toolName: call.toolName,
        calls: [call],
        count: 1,
        collapsed: true,
      })
    }
  }
  return groups
}

function estimateTokens(value: unknown): number {
  if (value == null) return 0
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  let ascii = 0
  let nonAscii = 0
  for (const char of text) {
    if (char.charCodeAt(0) <= 0x7f) ascii++
    else nonAscii++
  }
  return Math.ceil(ascii / 4 + nonAscii / 1.5)
}

function deriveTokenUsage(
  taskEvents: RunEvent[],
  fallbackInput: unknown,
  fallbackOutput: unknown,
) {
  const usageEvents = taskEvents.filter((event) => event.type === 'agent.usage')
  const input = usageEvents.reduce(
    (sum, event) => sum + Number(event.payload.input_tokens || 0),
    0,
  )
  const output = usageEvents.reduce(
    (sum, event) => sum + Number(event.payload.output_tokens || 0),
    0,
  )
  if (input > 0 || output > 0) {
    return { input, output, estimated: false }
  }
  return {
    input: estimateTokens(fallbackInput),
    output: estimateTokens(fallbackOutput),
    estimated: true,
  }
}

// ==================== 中间步骤派生 ====================

function deriveIntermediateSteps(events: RunEvent[]): IntermediateStep[] {
  const steps: IntermediateStep[] = []
  for (const e of events) {
    if (e.type === 'agent.message') {
      const text = e.payload.text as string | undefined
      if (text) {
        steps.push({
          id: `msg-${e.sequence}`,
          type: 'message',
          content: text,
          timestamp: e.timestamp,
          sequence: e.sequence,
        })
      }
    }
    if (e.type === 'tool.started') {
      const tool = e.payload.tool as string | undefined
      const input = (e.payload.input ?? {}) as Record<string, unknown>
      steps.push({
        id: `action-${e.sequence}`,
        type: 'action',
        content: `调用工具: ${tool || '未知'}`,
        timestamp: e.timestamp,
        sequence: e.sequence,
        action: { tool: tool || '未知', input },
      })
    }
    // 待后端补充: agent.thinking 事件 → type: 'thought'
    if (e.type === 'plan.created' || e.type === 'brain.contract_created') {
      const text = (e.payload.summary || e.payload.text || '') as string
      if (text) {
        steps.push({
          id: `thought-${e.sequence}`,
          type: 'thought',
          content: text,
          timestamp: e.timestamp,
          sequence: e.sequence,
        })
      }
    }
  }
  return steps.sort((a, b) => a.sequence - b.sequence)
}

// ==================== 错误分类 ====================

function classifyErrorType(errorText: string): TaskError['type'] {
  const lower = errorText.toLowerCase()
  if (lower.includes('timeout') || lower.includes('超时') || lower.match(/超过\d+秒/)) return 'TIMEOUT'
  if (lower.includes('cancel') || lower.includes('取消') || lower.includes('abort')) return 'USER_CANCEL'
  if (
    lower.includes('error') ||
    lower.includes('fail') ||
    lower.includes('exception') ||
    lower.includes('失败') ||
    lower.includes('错误')
  )
    return 'EXCEPTION'
  return 'UNKNOWN'
}

// ==================== 节点状态推导 ====================

function deriveNodeStatus(
  taskId: string,
  events: RunEvent[],
): NodeStatus {
  const hasCompleted = events.some(
    (e) => (e.type === 'agent.completed' || e.type === 'agent.failed') && e.task_id === taskId,
  )
  const hasFailed = events.some((e) => e.type === 'agent.failed' && e.task_id === taskId)
  const hasStarted = events.some(
    (e) => (e.type === 'agent.started' || e.type === 'agent.message' || e.type === 'tool.started') &&
      e.task_id === taskId,
  )

  if (hasFailed) return 'failed'
  if (hasCompleted) return 'completed'
  if (hasStarted) return 'running'
  return 'pending'
}

// ==================== 主导出：事件 → 执行图节点 ====================

export function useNodeGraph(
  events: ComputedRef<RunEvent[]>,
  activeRunId: ComputedRef<string | null>,
  conversationRuns?: ComputedRef<Array<{id:string; objective:string; status:string; parent_run_id?:string|null; turn_index?:number; final_answer?:string|null; created_at?:string}>>,
) {
  /**
   * 从 events + conversationRuns 构建节点列表。
   * 多轮对话时，每轮作为一个 turn 节点，父子 run 之间连边。
   */
  const nodes = computed<ExecutionNode[]>(() => {
    const allEvents = events.value
    const convRuns = [...(conversationRuns?.value || [])].sort((left, right) => {
      const turnDelta = (left.turn_index || 1) - (right.turn_index || 1)
      if (turnDelta !== 0) return turnDelta
      const createdDelta = String(left.created_at || '').localeCompare(String(right.created_at || ''))
      return createdDelta || left.id.localeCompare(right.id)
    })
    // 侧栏代表整段 conversation；重新进入时 activeRun 可能仍是根 run。
    // DAG 总览固定展示最新轮任务，避免刷新前后出现不同布局。
    const layoutRunId = convRuns.at(-1)?.id ?? activeRunId.value
    const graphEvents = layoutRunId
      ? allEvents.filter(event => event.run_id === layoutRunId)
      : allEvents

    // 0. 多轮对话 turn 节点
    const turnNodes: ExecutionNode[] = []
    if (convRuns.length > 1) {
      for (const cr of convRuns) {
        const turnIndex = cr.turn_index || 1
        turnNodes.push({
          id: `turn-${cr.id}`,
          type: 'conversation' as const,
          name: `第 ${turnIndex} 轮 · 用户`,
          sub: cr.objective.slice(0, 35),
          status: (cr.status as NodeStatus) || 'pending',
          parentId: cr.parent_run_id ? `turn-${cr.parent_run_id}` : null,
          agentId: 'brain',
          taskId: null,
          runId: cr.id,
          depth: turnIndex - 1,
          startedAt: cr.created_at ?? null,
          finishedAt: cr.status === 'completed' ? (cr.created_at ?? null) : null,
          durationMs: null,
          objective: cr.objective,
          summary: cr.final_answer || null,
          input: null,
          output: cr.final_answer ? { text: cr.final_answer } : null,
          error: cr.status === 'failed'
            ? { nodeId: `turn-${cr.id}`, type: 'UNKNOWN', message: '执行失败', stack: null }
            : null,
          hasError: cr.status === 'failed',
          hasToolCalls: false,
          toolCallCount: 0,
          intermediateSteps: [],
          toolCallGroups: [],
          dependsOn: cr.parent_run_id ? [`turn-${cr.parent_run_id}`] : [],
          interruptible: false,
          agentType: undefined,
          tokenUsage: deriveTokenUsage([], cr.objective, cr.final_answer),
        })
      }
    }

    // 1-6. (原有逻辑) 构建 orchestrator + agent 节点
    if (!graphEvents.length) return []

    // 1. 查找 plan.created 事件获取 DAG 定义
    const planEvent = graphEvents
      .slice()
      .reverse()
      .find((e) => e.type === 'plan.created')
    const tasks: PlanTask[] = (planEvent?.payload.tasks as PlanTask[] | undefined) ?? []
    const runId = layoutRunId || planEvent?.run_id || ''

    // 2. 按 task_id 分组事件
    const eventsByTask = new Map<string, RunEvent[]>()
    for (const e of graphEvents) {
      if (!e.task_id) continue
      const list = eventsByTask.get(e.task_id) || []
      list.push(e)
      eventsByTask.set(e.task_id, list)
    }

    // 3. 拓扑排序计算 depth
    const depthMap = new Map<string, number>()
    function getDepth(id: string, visited = new Set<string>()): number {
      if (visited.has(id)) return 0
      if (depthMap.has(id)) return depthMap.get(id)!
      visited.add(id)
      const task = tasks.find((t) => t.id === id)
      const deps = task?.depends_on ?? []
      let maxDep = 0
      for (const d of deps) {
        maxDep = Math.max(maxDep, getDepth(d, visited) + 1)
      }
      depthMap.set(id, maxDep)
      return maxDep
    }
    for (const t of tasks) getDepth(t.id)

    // 4. 收集没有任务的 agent 事件（如主脑事件）
    const plannerEvents = graphEvents.filter(
      (e) => e.type === 'planner.started' || e.type === 'plan.created',
    )
    const runCompleted = graphEvents.some((e) => e.type === 'run.completed')
    const runFailed = graphEvents.some((e) => e.type === 'run.failed')

    // 5. 构建 Orchestrator 节点 (主脑)
    // 主脑固定接在当前轮次后；状态、摘要和完成时间更新不得改变 depth。
    const activeTurnNode = turnNodes.find(node => node.runId === runId)
      ?? turnNodes.at(-1)
    const depthOffset = activeTurnNode ? activeTurnNode.depth + 1 : 0
    const orchestratorNode: ExecutionNode = {
      id: `orchestrator-${runId}`,
      type: 'orchestrator',
      name: '主脑编排',
      sub: tasks.length ? `${tasks.length} 个任务` : runCompleted ? '直接回答' : '规划中',
      status: tasks.length || runCompleted ? 'completed' : runFailed ? 'failed' : plannerEvents.length ? 'running' : 'pending',
      parentId: activeTurnNode?.id ?? null,
      agentId: 'brain',
      taskId: null,
      runId,
      depth: depthOffset,
      startedAt: plannerEvents[0]?.timestamp || null,
      finishedAt: planEvent?.timestamp || null,
      durationMs: null,
      objective: null,
      summary: (planEvent?.payload.summary as string) || null,
      input: planEvent?.payload.llm_input ? { llmPrompt: planEvent.payload.llm_input } : null,
      output: planEvent?.payload ? { tasks: planEvent.payload.tasks, summary: planEvent.payload.summary } : null,
      error: null,
      hasError: false,
      hasToolCalls: false,
      toolCallCount: 0,
      intermediateSteps: deriveIntermediateSteps(plannerEvents),
      toolCallGroups: [],
      dependsOn: activeTurnNode ? [activeTurnNode.id] : [],
      interruptible: false,
      agentType: undefined,
      tokenUsage: deriveTokenUsage(
        plannerEvents,
        plannerEvents.map(event => event.payload),
        planEvent?.payload,
      ),
    }

    // 6. 构建 Agent 节点
    const agentNodes: ExecutionNode[] = tasks.map((task) => {
      const taskEvents = eventsByTask.get(task.id) || []

      // 提取 tool.started 事件
      const rawToolCalls: ToolCall[] = taskEvents
        .filter((e) => e.type === 'tool.started')
        .map((e) => ({
          id: `tool-${e.sequence}`,
          toolName: (e.payload.tool as string) || '未知',
          input: (e.payload.input ?? {}) as Record<string, unknown>,
          output: null, // 待后端补充: tool.completed
          status: 'running' as const, // 待后端补充: tool.completed/failed
          startedAt: e.timestamp,
          finishedAt: null,
          durationMs: null,
          error: null,
        }))

      const toolGroups = groupToolCalls(rawToolCalls)
      const steps = deriveIntermediateSteps(taskEvents)

      // 提取错误信息
      const failedEvent = taskEvents.find((e) => e.type === 'agent.failed')
      let error: TaskError | null = null
      if (failedEvent) {
        let errorMsg =
          (failedEvent.payload.error as string) ||
          (failedEvent.payload.summary as string) ||
          'Agent 执行错误'
        if (errorMsg.includes('Claude Code returned an error result: success')) {
          const apiErrorEvent = [...taskEvents].reverse().find(
            event => event.type === 'agent.message'
              && String(event.payload.text || '').trim().toLowerCase().startsWith('api error:'),
          )
          if (apiErrorEvent) errorMsg = String(apiErrorEvent.payload.text)
        }
        error = {
          nodeId: `task-${task.id}`,
          type: classifyErrorType(errorMsg),
          message: errorMsg,
          stack: null, // 待后端补充
        }
      }

      // 提取完成信息
      const completedEvent = taskEvents.find((e) => e.type === 'agent.completed')
      const startedEvent = taskEvents.find((e) => e.type === 'agent.started')
      const messageOutput = taskEvents
        .filter((event) => event.type === 'agent.message')
        .map((event) => event.payload.text)

      return {
        id: `task-${task.id}`,
        type: 'agent' as const,
        name: task.agent,
        sub: task.title,
        status: deriveNodeStatus(task.id, taskEvents),
        parentId: orchestratorNode.id,
        agentId: task.agent,
        taskId: task.id,
        runId,
        depth: (depthMap.get(task.id) ?? 0) + depthOffset + 1, // 排在 turn 节点 + orchestrator 右侧
        startedAt: startedEvent?.timestamp || null,
        finishedAt: completedEvent?.timestamp || null,
        durationMs:
          completedEvent?.payload?.duration_ms != null
            ? (completedEvent.payload.duration_ms as number)
            : null,
        objective: task.objective,
        summary: (completedEvent?.payload.summary as string) || null,
        input: { objective: task.objective, depends_on: task.depends_on, write_scope: task.write_scope },
        output: completedEvent?.payload
          ? {
              status: completedEvent.payload.status,
              summary: completedEvent.payload.summary,
              changed_files: completedEvent.payload.changed_files,
              provides: completedEvent.payload.provides,
            }
          : null,
        error,
        hasError: error !== null,
        hasToolCalls: rawToolCalls.length > 0,
        toolCallCount: rawToolCalls.length,
        intermediateSteps: steps,
        toolCallGroups: toolGroups,
        dependsOn: task.depends_on.map((d) => `task-${d}`),
        interruptible: true,
        agentType: task.agent_type || undefined,
        tokenUsage: deriveTokenUsage(
          taskEvents,
          {
            objective: task.objective,
            depends_on: task.depends_on,
            write_scope: task.write_scope,
          },
          messageOutput.length ? messageOutput : completedEvent?.payload,
        ),
      }
    })

    return [...turnNodes, orchestratorNode, ...agentNodes]
  })

  /**
   * 从节点列表派生依赖边
   * 自动添加 orchestrator→leaf-task 的边，保证所有节点都有连线
   */
  const edges = computed<NodeEdge[]>(() => {
    const deps = nodes.value.flatMap((node) =>
      node.dependsOn.map((from) => ({
        from,
        to: node.id,
        label: node.type === 'agent' ? '依赖' : undefined,
      })),
    )
    // 只给真正的执行 Agent 补主脑连线；conversation 节点有自己的轮次链。
    const leafIds = new Set(
      nodes.value
        .filter(n => n.type === 'agent' && n.dependsOn.length === 0)
        .map(n => n.id),
    )
    const hasEdgeTo = new Set(deps.map(e => e.to))
    const orchestrator = nodes.value.find(n => n.type === 'orchestrator')
    if (orchestrator) {
      for (const leafId of leafIds) {
        if (!hasEdgeTo.has(leafId)) {
          deps.push({ from: orchestrator.id, to: leafId, label: undefined })
        }
      }
    }
    return deps
  })

  /**
   * 按 node_id 索引的工具调用分组
   */
  const toolCallGroupsByNode = computed<Map<string, ToolCallGroup[]>>(() => {
    const map = new Map<string, ToolCallGroup[]>()
    for (const node of nodes.value) {
      if (node.toolCallGroups.length) {
        map.set(node.id, node.toolCallGroups)
      }
    }
    return map
  })

  /**
   * 按 node_id 索引的中间步骤
   */
  const intermediateStepsByNode = computed<Map<string, IntermediateStep[]>>(() => {
    const map = new Map<string, IntermediateStep[]>()
    for (const node of nodes.value) {
      if (node.intermediateSteps.length) {
        map.set(node.id, node.intermediateSteps)
      }
    }
    return map
  })

  /**
   * 从节点列表中查找节点
   */
  function findNode(nodeId: string): ExecutionNode | undefined {
    return nodes.value.find((n) => n.id === nodeId)
  }

  /**
   * 筛选后的节点列表
   */
  function filterNodes(filterStatus: string): ExecutionNode[] {
    if (!filterStatus || filterStatus === 'all') return nodes.value
    return nodes.value.filter((n) => n.status === filterStatus)
  }

  return {
    nodes,
    edges,
    toolCallGroupsByNode,
    intermediateStepsByNode,
    findNode,
    filterNodes,
  }
}
