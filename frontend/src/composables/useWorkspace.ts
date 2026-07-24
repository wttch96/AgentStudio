import { computed, onBeforeUnmount, reactive } from 'vue'
import { api } from '../api/client'
import type {
  AgentProfile,
  ActiveAgent,
  ConversationTurn,
  DeepSeekBalance,
  DeepSeekUsage,
  MemoryCompactionRecord,
  PlanTask,
  Run,
  RunEvent,
  SkillProfile,
  StreamingState,
  SystemStatus,
} from '../types'

interface WorkspaceState {
  runs: Run[]
  activeRun: Run | null
  events: RunEvent[]          // 当前活跃 run 的事件（兼容旧引用）
  projectId: string
  projectName: string
  agents: AgentProfile[]
  skills: SkillProfile[]
  status: SystemStatus | null
  deepseekBalance: DeepSeekBalance | null
  deepseekUsage: DeepSeekUsage | null
  balanceLoading: boolean
  loading: boolean
  submitting: boolean
  error: string
  taskQueue: { id: string; objective: string }[]
  // 新增：conversation 级别状态
  conversationRootId: string | null
  conversationRuns: Run[]
  conversationEvents: RunEvent[]
  // 派生状态
  conversationTurns: ConversationTurn[]
  streamingState: StreamingState
  memoryCompactions: MemoryCompactionRecord[]
  activeAgents: ActiveAgent[]
}

const state = reactive<WorkspaceState>({
  runs: [],
  activeRun: null,
  events: [],
  projectId: '',
  projectName: '',

  agents: [],
  taskQueue: [],
  skills: [],
  status: null,
  deepseekBalance: null,
  deepseekUsage: null,
  balanceLoading: false,
  loading: true,
  submitting: false,
  error: '',

  conversationRootId: null,
  conversationRuns: [],
  conversationEvents: [],

  conversationTurns: [],
  streamingState: {
    activeTurnId: null,
    thinkingText: '',
    responseText: '',
    isStreaming: false,
  },
  memoryCompactions: [],
  activeAgents: [],
})

let eventSource: EventSource | null = null

export function useWorkspace() {
  async function initialize() {
    state.loading = true
    state.error = ''
    try {
      const [status, agents, skills, runs] = await Promise.all([
        api.status(),
        api.agents(state.projectId || undefined),
        api.skills(state.projectId || undefined),
        api.runs(),
      ])
      state.status = status
      state.agents = agents
      state.skills = skills
      state.runs = runs
      if (runs[0]) await selectRun(runs[0].id)
      void refreshDeepSeekBalance()
      void refreshDeepSeekUsage()
    } catch (error) {
      state.error = error instanceof Error ? error.message : '初始化失败'
    } finally {
      state.loading = false
    }
  }

  async function refreshConfiguration() {
    try {
      const [agents, skills, status] = await Promise.all([
        api.agents(state.projectId || undefined),
        api.skills(state.projectId || undefined),
        api.status(),
      ])
      state.agents = agents
      state.skills = skills
      state.status = status
    } catch {
      // 后台刷新失败不覆盖已有数据
    }
  }

  async function refreshDeepSeekBalance(refresh = false) {
    state.balanceLoading = true
    try {
      state.deepseekBalance = await api.deepseekBalance(refresh)
    } catch (error) {
      state.deepseekBalance = {
        configured: state.status?.deepseek_configured ?? false,
        available: false,
        infos: [],
        error: error instanceof Error ? error.message : '余额读取失败',
      }
    } finally {
      state.balanceLoading = false
    }
  }

  async function refreshDeepSeekUsage() {
    try {
      state.deepseekUsage = await api.deepseekUsage()
    } catch {
      // 本地统计是辅助信息；短暂失败时保留上一次成功结果。
    }
  }

  // ==================== Conversation 级别事件加载 ====================

  async function loadConversationEvents(conversationId: string) {
    try {
      const data = await api.conversation(conversationId)
      const allEvents: RunEvent[] = []
      const allRuns: Run[] = []
      for (const run of data.runs) {
        allRuns.push(run as Run)
        for (const ev of run.events) {
          allEvents.push(ev)
        }
      }
      state.conversationRuns = allRuns.sort(
        (a, b) => (a.turn_index || 1) - (b.turn_index || 1),
      )
      state.conversationEvents = deduplicate(allEvents)
      state.conversationRootId = data.runs[0]?.id || null
      // 保持 events 引用指向当前活跃 run 的事件
      const active = state.conversationRuns.find(r => r.id === state.activeRun?.id)
      if (active) {
        state.events = allEvents.filter(e => e.run_id === active.id)
      }
    } catch {
      // 静默处理：可能后台还没启动
    }
  }

  // ==================== 派生状态：从 conversation events 重建对话轮次 ====================

  function deriveConversationTurns(runs: Run[], events: RunEvent[]): ConversationTurn[] {
    // 按 run_id 分组 events
    const eventsByRun = new Map<string, RunEvent[]>()
    for (const e of events) {
      const list = eventsByRun.get(e.run_id) || []
      list.push(e)
      eventsByRun.set(e.run_id, list)
    }

    return runs.map((run) => {
      const runEvents = eventsByRun.get(run.id) || []
      const sorted = [...runEvents].sort((a, b) => a.sequence - b.sequence)

      // 提取计划任务
      const planEvent = sorted.find((e) => e.type === 'plan.created')
      const planTasks: PlanTask[] = (planEvent?.payload.tasks as PlanTask[] | undefined) ?? []

      // 提取思考文本 — 收集主脑的全部规划输出
      const plannerStarted = sorted.find((e) => e.type === 'planner.started')
      const thinkingParts: string[] = []
      if (plannerStarted) thinkingParts.push('DeepSeek 主脑规划中…')
      if (planEvent) {
        const summary = planEvent.payload.summary as string | undefined
        if (summary) thinkingParts.push(summary)
        const contract = planEvent.payload.coordination_contract as string | undefined
        if (contract) thinkingParts.push('共享契约：\n' + contract)
        thinkingParts.push(`生成 ${planTasks.length} 个任务`)
      }
      // 收集 agent 执行过程中的所有文本输出作为思考过程
      for (const e of sorted) {
        if (e.type === 'agent.message' && typeof e.payload?.text === 'string') {
          const txt = (e.payload.text as string).slice(0, 500)
          if (txt.trim()) thinkingParts.push(`[${e.agent_id || 'agent'}]: ${txt}`)
        }
      }
      const thinkingText = thinkingParts.length ? thinkingParts.join('\n') : null

      // 提取大脑响应 — 包含主脑的最终汇总
      const summaryEvent = sorted.find((e) => e.type === 'run.summary')
      const brainSynthesizing = sorted.find((e) => e.type === 'brain.synthesizing')
      const planSummary = (planEvent?.payload.summary as string) || ''
      const brainResponse = run.final_answer
        || (summaryEvent?.payload.text as string)
        || (brainSynthesizing?.payload.text as string)
        || planSummary
        || null

      // 提取记忆压缩事件
      const memoryEvents: MemoryCompactionRecord[] = sorted
        .filter((e) => e.type === 'memory.compacted')
        .map((e) => ({
          wave: (e.payload.wave as number) || 0,
          agentsCompacted: (e.payload.agents as string[]) || (e.payload.agent ? [e.payload.agent as string] : []),
          tokenCountBefore: (e.payload.token_count_before as number) || null,
          tokenCountAfter: (e.payload.token_count_after as number) || null,
          timestamp: e.timestamp,
        }))

      // 统计波浪数
      const waveEvents = sorted.filter((e) => e.type === 'wave.started')
      const waveCount = waveEvents.length

      // 确定状态
      let status: ConversationTurn['status'] = 'complete'
      if (run.status === 'failed') status = 'error'
      else if (run.status === 'cancelled') status = 'error'
      else if (run.status === 'running') {
        if (sorted.some((e) => e.type === 'agent.completed')) status = 'executing'
        else if (sorted.some((e) => e.type === 'plan.created')) status = 'executing'
        else if (sorted.some((e) => e.type === 'planner.started')) status = 'thinking'
      } else if (run.status === 'queued') {
        status = 'thinking'
      }

      return {
        id: `turn-${run.id}`,
        runId: run.id,
        userMessage: run.objective,
        brainResponse,
        thinkingText,
        status,
        planTasks,
        waveCount,
        memoryEvents,
        createdAt: run.created_at,
        completedAt: ['completed', 'failed', 'cancelled'].includes(run.status) ? run.updated_at : null,
      }
    })
  }

  // ==================== 派生状态：活跃 Agent 列表 ====================

  function deriveActiveAgents(events: RunEvent[], tasks: PlanTask[]): ActiveAgent[] {
    const started = new Map<string, { taskId: string; title: string; startedAt: string }>()
    const completed = new Set<string>()
    const failed = new Set<string>()

    for (const e of events) {
      if (e.type === 'agent.started' && e.agent_id) {
        started.set(e.agent_id, {
          taskId: e.task_id || '',
          title: (e.payload.title as string) || tasks.find(t => t.id === e.task_id)?.title || '',
          startedAt: e.timestamp,
        })
      }
      if (e.type === 'agent.completed' && e.agent_id) {
        completed.add(e.agent_id)
      }
      if (e.type === 'agent.failed' && e.agent_id) {
        failed.add(e.agent_id)
      }
    }

    return [...started.entries()]
      .filter(([name]) => !completed.has(name) && !failed.has(name))
      .map(([name, info]) => ({
        name,
        taskId: info.taskId,
        title: info.title,
        status: 'running' as const,
        startedAt: info.startedAt,
      }))
  }

  function refreshDerivedState() {
    // 使用 conversation 级别数据计算对话轮次
    state.conversationTurns = deriveConversationTurns(
      state.conversationRuns.length ? state.conversationRuns : (state.activeRun ? [state.activeRun] : []),
      state.conversationEvents.length ? state.conversationEvents : state.events,
    )
    const allEvents = state.conversationEvents.length ? state.conversationEvents : state.events
    state.memoryCompactions = allEvents
      .filter((e) => e.type === 'memory.compacted')
      .map((e) => ({
        wave: (e.payload.wave as number) || 0,
        agentsCompacted: (e.payload.agents as string[]) || (e.payload.agent ? [e.payload.agent as string] : []),
        tokenCountBefore: (e.payload.token_count_before as number) || null,
        tokenCountAfter: (e.payload.token_count_after as number) || null,
        timestamp: e.timestamp,
      }))
    state.activeAgents = deriveActiveAgents(allEvents, plan.value)
  }

  // ==================== 事件处理：处理所有事件类型更新派生状态 ====================

  function applyAllEvents(event: RunEvent) {
    // 更新流式状态
    if (state.streamingState.activeTurnId) {
      if (event.type === 'agent.message') {
        const text = event.payload.text as string | undefined
        if (text) {
          state.streamingState.responseText += text
        }
      } else if (event.type === 'planner.started') {
        state.streamingState.thinkingText = 'DeepSeek 主脑规划中…'
        state.streamingState.isStreaming = true
      } else if (event.type === 'plan.created') {
        const tasks = (event.payload.tasks as PlanTask[] | undefined) ?? []
        state.streamingState.thinkingText = `已生成 ${tasks.length} 个任务`
      } else if (event.type === 'agent.started') {
        state.streamingState.thinkingText += `\n启动 Agent: ${event.agent_id || 'unknown'}`
      }
    }

    // 处理终端事件
    if (event.type.startsWith('run.')) {
      const terminal = event.type.replace('run.', '')
      if (['completed', 'failed', 'cancelled'].includes(terminal)) {
        if (state.activeRun) {
          state.activeRun.status = terminal as Run['status']
          const text = event.payload.text
          if (typeof text === 'string') state.activeRun.final_answer = text
          // 失败时提取错误原因
          if (terminal === 'failed') {
            const errorDetail = (event.payload.error as string) || (event.payload.summary as string) || event.payload.text as string || ''
            if (typeof errorDetail === 'string' && errorDetail) {
              state.error = errorDetail
            }
          }
          replaceRun(state.activeRun)
        }
        state.streamingState.isStreaming = false
        closeStream()
        void refreshDeepSeekBalance()
        void refreshDeepSeekUsage()
        // 自动推进队列中的下一个任务 — 作为当前 conversation 的下一轮
        if (state.taskQueue.length > 0) {
          const next = state.taskQueue.shift()!
          void _startRun(next.objective)
        }
      } else if (event.type === 'run.started') {
        if (state.activeRun) {
          state.activeRun.status = 'running'
          replaceRun(state.activeRun)
        }
      }
    }

    // 每次事件后刷新派生状态
    refreshDerivedState()
  }

  // ==================== 运行管理 ====================

  async function selectRun(runId: string) {
    closeStream()
    state.error = ''
    try {
      const run = await api.run(runId)
      state.activeRun = run
      state.events = deduplicate(run.events)

      // 加载同一 conversation 的所有 runs
      const conversationId = run.conversation_id || run.id
      if (run.conversation_runs && run.conversation_runs.length > 1) {
        // 后端已附带 conversation 摘要，完整加载
        await loadConversationEvents(conversationId)
      } else {
        state.conversationRuns = [run]
        state.conversationEvents = [...state.events]
        state.conversationRootId = null
      }

      // 初始化流式状态
      state.streamingState = {
        activeTurnId: `turn-${run.id}`,
        thinkingText: '',
        responseText: run.final_answer || '',
        isStreaming: run.status === 'running' || run.status === 'queued',
      }
      refreshDerivedState()
      if (run.status === 'queued' || run.status === 'running') openStream(runId)
    } catch (error) {
      state.error = error instanceof Error ? error.message : '读取运行失败'
    }
  }

  async function _startRun(objective: string) {
    try {
      // 关键：如果有 conversation 上下文，以最后一轮为 parent 继续
      let parentRunId: string | undefined
      if (state.conversationRuns.length > 0) {
        // 找到最后一个终态的 run
        const lastDone = [...state.conversationRuns]
          .reverse()
          .find(r => ['completed', 'failed', 'cancelled'].includes(r.status))
        parentRunId = lastDone?.id ?? state.activeRun?.id
      } else if (state.activeRun && ['completed', 'failed', 'cancelled'].includes(state.activeRun.status)) {
        parentRunId = state.activeRun.id
      }

      const run = await api.createRun(objective, parentRunId, state.projectId || undefined)
      // 继续对话的轮次属于同一 conversation，不产生新的侧边栏条目
      if (!parentRunId) {
        state.runs.unshift(run)
      }
      state.activeRun = run
      state.events = []

      // 维护 conversation 状态
      if (state.conversationRuns.length > 0) {
        state.conversationRuns.push(run)
      } else {
        state.conversationRuns = [run]
      }
      state.conversationEvents = [...(state.conversationEvents.length ? state.conversationEvents : [])]
      state.conversationRootId = state.conversationRuns[0].id

      state.streamingState = {
        activeTurnId: `turn-${run.id}`,
        thinkingText: '',
        responseText: '',
        isStreaming: true,
      }
      refreshDerivedState()
      openStream(run.id)
    } catch (error) {
      state.error = error instanceof Error ? error.message : '创建运行失败'
      throw error
    }
  }

  async function createRun(objective: string) {
    state.submitting = true
    state.error = ''
    try {
      // 如果有活跃任务，发送中断引导指令到当前任务
      if (state.activeRun && !['completed', 'failed', 'cancelled'].includes(state.activeRun.status)) {
        await api.interruptRun(state.activeRun.id, {
          target: 'all',
          action: 'inject',
          instruction: objective,
        })
        const qid = Date.now().toString(36)
        state.taskQueue.push({ id: qid, objective })
        state.submitting = false
        return
      }
      await _startRun(objective)
    } catch (error) {
      state.error = error instanceof Error ? error.message : '创建运行失败'
      throw error
    } finally {
      state.submitting = false
    }
  }

  function removeFromQueue(qid: string) {
    state.taskQueue = state.taskQueue.filter(q => q.id !== qid)
  }

  function promoteQueueItem(qid: string) {
    const idx = state.taskQueue.findIndex(q => q.id === qid)
    if (idx < 0) return
    const item = state.taskQueue[idx]
    state.taskQueue.splice(idx, 1)
    cancelActiveRun().then(() => _startRun(item.objective))
  }

  function beginNewRun() {
    // 开始全新 conversation
    closeStream()
    state.activeRun = null
    state.events = []
    state.conversationRuns = []
    state.conversationEvents = []
    state.conversationRootId = null
    state.streamingState = {
      activeTurnId: null,
      thinkingText: '',
      responseText: '',
      isStreaming: false,
    }
    state.memoryCompactions = []
    state.conversationTurns = []
    state.activeAgents = []
    state.error = ''
  }

  async function cancelActiveRun() {
    if (!state.activeRun) return
    try {
      await api.cancelRun(state.activeRun.id)
    } catch (error) {
      state.error = error instanceof Error ? error.message : '取消失败'
    }
  }

  async function deleteRun(runId: string) {
    state.error = ''
    try {
      await api.deleteRun(runId)
      const deletingActive = state.activeRun?.id === runId
      state.runs = state.runs.filter((run) => run.id !== runId)
      // 从 conversation runs 中移除
      state.conversationRuns = state.conversationRuns.filter(r => r.id !== runId)

      if (!deletingActive) {
        refreshDerivedState()
        return
      }

      closeStream()
      state.activeRun = null
      state.events = []
      state.streamingState = {
        activeTurnId: null,
        thinkingText: '',
        responseText: '',
        isStreaming: false,
      }
      if (state.runs[0]) await selectRun(state.runs[0].id)
      else beginNewRun()
    } catch (error) {
      state.error = error instanceof Error ? error.message : '删除运行失败'
    }
  }

  // ==================== SSE 流式连接 ====================

  function openStream(runId: string) {
    closeStream()
    const after = state.events.at(-1)?.sequence ?? 0
    eventSource = new EventSource(api.streamUrl(runId, after))
    eventSource.addEventListener('run-event', (message) => {
      const event = JSON.parse((message as MessageEvent).data) as RunEvent
      if (!state.events.some((item) => item.sequence === event.sequence)) {
        state.events.push(event)
      }
      // 始终同步到 conversation events（保持 conversation 上下文完整）
      const convIdx = state.conversationEvents.findIndex(
        e => e.run_id === event.run_id && e.sequence === event.sequence,
      )
      if (convIdx < 0) {
        state.conversationEvents.push(event)
      }
      applyAllEvents(event)
    })
    eventSource.onerror = () => {
      void refreshActiveRun()
    }
  }

  async function refreshActiveRun() {
    if (!state.activeRun) return
    try {
      const run = await api.run(state.activeRun.id)
      state.activeRun = run
      state.events = deduplicate([...state.events, ...run.events])
      replaceRun(run)
      // 同步更新 conversation events
      if (state.conversationEvents.length > 0) {
        const convIds = new Set(state.conversationEvents.map(e => `${e.run_id}:${e.sequence}`))
        for (const ev of run.events) {
          if (!convIds.has(`${ev.run_id}:${ev.sequence}`)) {
            state.conversationEvents.push(ev)
          }
        }
      }
      refreshDerivedState()
      if (['completed', 'failed', 'cancelled'].includes(run.status)) closeStream()
    } catch {
      // 短暂断线不覆盖当前界面，等待 EventSource 下一次重连。
    }
  }

  function replaceRun(run: Run) {
    const index = state.runs.findIndex((item) => item.id === run.id)
    if (index >= 0) state.runs[index] = run
    // 同步更新 conversation runs
    const convIdx = state.conversationRuns.findIndex(item => item.id === run.id)
    if (convIdx >= 0) state.conversationRuns[convIdx] = run
  }

  function closeStream() {
    eventSource?.close()
    eventSource = null
  }

  function deduplicate(events: RunEvent[]) {
    return [...new Map(events.map((event) => [event.sequence, event])).values()].sort(
      (left, right) => left.sequence - right.sequence,
    )
  }

  // ==================== 计算属性 ====================

  const latestPlanEvent = computed(() =>
    [...state.conversationEvents, ...state.events].reverse().find((item) => item.type === 'plan.created'),
  )
  const plan = computed<PlanTask[]>(() =>
    (latestPlanEvent.value?.payload.tasks as PlanTask[] | undefined) ?? [],
  )
  const planContract = computed(() => {
    const value = latestPlanEvent.value?.payload.coordination_contract
    return typeof value === 'string' ? value : ''
  })

  const agentEvents = computed(() =>
    [...state.conversationEvents, ...state.events].filter((event) => event.agent_id),
  )
  const isRunning = computed(() => ['queued', 'running'].includes(state.activeRun?.status ?? ''))

  onBeforeUnmount(closeStream)

  return {
    state,
    plan,
    planContract,
    agentEvents,
    isRunning,
    initialize,
    selectRun,
    createRun,
    beginNewRun,
    cancelActiveRun,
    deleteRun,
    removeFromQueue,
    promoteQueueItem,
    refreshConfiguration,
    refreshDeepSeekBalance,
    refreshDeepSeekUsage,
    refreshDerivedState,
  }
}
