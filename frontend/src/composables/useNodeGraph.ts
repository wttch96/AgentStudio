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
    const convRuns = conversationRuns?.value || []

    // 0. 多轮对话 turn 节点
    const turnNodes: ExecutionNode[] = []
    if (convRuns.length > 1) {
      for (const cr of convRuns) {
        const isActive = cr.id === activeRunId.value
        turnNodes.push({
          id: `turn-${cr.id}`,
          type: 'agent' as const,
          name: cr.objective.slice(0, 30),
          sub: `轮次 ${cr.turn_index || '?'} · ${cr.status}`,
          status: (cr.status as NodeStatus) || 'pending',
          parentId: cr.parent_run_id ? `turn-${cr.parent_run_id}` : null,
          agentId: 'brain',
          taskId: null,
          runId: cr.id,
          depth: (cr.turn_index || 1) - 1,  // 从左往右排列：turn 1 在 depth 0, turn 2 在 depth 1...
          startedAt: cr.created_at || null,
          finishedAt: cr.status === 'completed' ? cr.created_at : null,
          durationMs: null,
          objective: cr.objective,
          summary: cr.final_answer || null,
          input: null,
          output: cr.final_answer ? { text: cr.final_answer } : null,
          error: cr.status === 'failed' ? { nodeId: `turn-${cr.id}`, type: 'error', message: '执行失败' } : null,
          hasError: cr.status === 'failed',
          hasToolCalls: false,
          toolCallCount: 0,
          intermediateSteps: [],
          toolCallGroups: [],
          dependsOn: cr.parent_run_id ? [`turn-${cr.parent_run_id}`] : [],
          interruptible: false,
        })
      }
    }

    // 1-6. (原有逻辑) 构建 orchestrator + agent 节点
    if (!allEvents.length) return []

    // 1. 查找 plan.created 事件获取 DAG 定义
    const planEvent = allEvents
      .slice()
      .reverse()
      .find((e) => e.type === 'plan.created')
    const tasks: PlanTask[] = (planEvent?.payload.tasks as PlanTask[] | undefined) ?? []
    const runId = activeRunId.value || planEvent?.run_id || ''

    // 2. 按 task_id 分组事件
    const eventsByTask = new Map<string, RunEvent[]>()
    for (const e of allEvents) {
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
    const plannerEvents = allEvents.filter(
      (e) => e.type === 'planner.started' || e.type === 'plan.created',
    )
    const runCompleted = allEvents.some((e) => e.type === 'run.completed')
    const runFailed = allEvents.some((e) => e.type === 'run.failed')

    // 5. 构建 Orchestrator 节点 (主脑)
    // depth 偏移：排在对话 turn 节点右侧
    const depthOffset = turnNodes.length
    const orchestratorNode: ExecutionNode = {
      id: `orchestrator-${runId}`,
      type: 'orchestrator',
      name: '主脑编排',
      sub: tasks.length ? `${tasks.length} 个任务` : runCompleted ? '直接回答' : '规划中',
      status: tasks.length || runCompleted ? 'completed' : runFailed ? 'failed' : plannerEvents.length ? 'running' : 'pending',
      parentId: null,
      agentId: 'brain',
      taskId: null,
      runId,
      depth: depthOffset,
      startedAt: plannerEvents[0]?.timestamp || null,
      finishedAt: planEvent?.timestamp || null,
      durationMs: null,
      objective: null,
      summary: (planEvent?.payload.summary as string) || null,
      input: null,
      output: planEvent?.payload ? { tasks: planEvent.payload.tasks, summary: planEvent.payload.summary } : null,
      error: null,
      hasError: false,
      hasToolCalls: false,
      toolCallCount: 0,
      intermediateSteps: deriveIntermediateSteps(plannerEvents),
      toolCallGroups: [],
      dependsOn: [],
      interruptible: false,
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
        const errorMsg =
          (failedEvent.payload.error as string) ||
          (failedEvent.payload.summary as string) ||
          'Agent 执行错误'
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
      }
    })

    return [...turnNodes, orchestratorNode, ...agentNodes]
  })

  /**
   * 从节点列表派生依赖边
   */
  const edges = computed<NodeEdge[]>(() => {
    return nodes.value.flatMap((node) =>
      node.dependsOn.map((from) => ({
        from,
        to: node.id,
        label: node.type === 'agent' ? '依赖' : undefined,
      })),
    )
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
