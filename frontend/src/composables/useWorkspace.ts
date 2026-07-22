import { computed, onBeforeUnmount, reactive } from 'vue'
import { api } from '../api/client'
import type {
  AgentProfile,
  DeepSeekBalance,
  DeepSeekUsage,
  PlanTask,
  Run,
  RunEvent,
  SkillProfile,
  SystemStatus,
} from '../types'

interface WorkspaceState {
  runs: Run[]
  activeRun: Run | null
  events: RunEvent[]
  agents: AgentProfile[]
  skills: SkillProfile[]
  status: SystemStatus | null
  deepseekBalance: DeepSeekBalance | null
  deepseekUsage: DeepSeekUsage | null
  balanceLoading: boolean
  loading: boolean
  submitting: boolean
  error: string
}

const state = reactive<WorkspaceState>({
  runs: [],
  activeRun: null,
  events: [],
  agents: [],
  skills: [],
  status: null,
  deepseekBalance: null,
  deepseekUsage: null,
  balanceLoading: false,
  loading: true,
  submitting: false,
  error: '',
})

let eventSource: EventSource | null = null

export function useWorkspace() {
  async function initialize() {
    state.loading = true
    state.error = ''
    try {
      const [status, agents, skills, runs] = await Promise.all([
        api.status(),
        api.agents(),
        api.skills(),
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
    const [agents, skills, status] = await Promise.all([api.agents(), api.skills(), api.status()])
    state.agents = agents
    state.skills = skills
    state.status = status
  }

  async function refreshDeepSeekBalance(refresh = false) {
    state.balanceLoading = true
    try {
      state.deepseekBalance = await api.deepseekBalance(refresh)
    } catch (error) {
      // 余额是辅助信息，失败时只在卡片内呈现，不覆盖工作台主错误状态。
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

  async function selectRun(runId: string) {
    closeStream()
    state.error = ''
    try {
      const run = await api.run(runId)
      state.activeRun = run
      state.events = deduplicate(run.events)
      if (run.status === 'queued' || run.status === 'running') openStream(runId)
    } catch (error) {
      state.error = error instanceof Error ? error.message : '读取运行失败'
    }
  }

  async function createRun(objective: string) {
    state.submitting = true
    state.error = ''
    try {
      const parentRunId =
        state.activeRun && ['completed', 'failed', 'cancelled'].includes(state.activeRun.status)
          ? state.activeRun.id
          : undefined
      const run = await api.createRun(objective, parentRunId)
      state.runs.unshift(run)
      state.activeRun = run
      state.events = []
      openStream(run.id)
    } catch (error) {
      state.error = error instanceof Error ? error.message : '创建运行失败'
      throw error
    } finally {
      state.submitting = false
    }
  }

  function beginNewRun() {
    closeStream()
    state.activeRun = null
    state.events = []
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
      if (!deletingActive) return

      closeStream()
      state.activeRun = null
      state.events = []
      if (state.runs[0]) await selectRun(state.runs[0].id)
    } catch (error) {
      state.error = error instanceof Error ? error.message : '删除运行失败'
    }
  }

  function openStream(runId: string) {
    closeStream()
    const after = state.events.at(-1)?.sequence ?? 0
    eventSource = new EventSource(api.streamUrl(runId, after))
    eventSource.addEventListener('run-event', (message) => {
      const event = JSON.parse((message as MessageEvent).data) as RunEvent
      if (!state.events.some((item) => item.sequence === event.sequence)) state.events.push(event)
      applyTerminalEvent(event)
    })
    eventSource.onerror = () => {
      // 浏览器会自动重连；若运行已经结束，主动同步并关闭连接。
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
      if (['completed', 'failed', 'cancelled'].includes(run.status)) closeStream()
    } catch {
      // 短暂断线不覆盖当前界面，等待 EventSource 下一次重连。
    }
  }

  function applyTerminalEvent(event: RunEvent) {
    if (!state.activeRun || !event.type.startsWith('run.')) return
    const terminal = event.type.replace('run.', '')
    if (['completed', 'failed', 'cancelled'].includes(terminal)) {
      state.activeRun.status = terminal as Run['status']
      const text = event.payload.text
      if (typeof text === 'string') state.activeRun.final_answer = text
      replaceRun(state.activeRun)
      closeStream()
      void refreshDeepSeekBalance()
      void refreshDeepSeekUsage()
    } else if (event.type === 'run.started') {
      state.activeRun.status = 'running'
      replaceRun(state.activeRun)
    }
  }

  function replaceRun(run: Run) {
    const index = state.runs.findIndex((item) => item.id === run.id)
    if (index >= 0) state.runs[index] = run
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

  const latestPlanEvent = computed(() =>
    [...state.events].reverse().find((item) => item.type === 'plan.created'),
  )
  const plan = computed<PlanTask[]>(() =>
    (latestPlanEvent.value?.payload.tasks as PlanTask[] | undefined) ?? [],
  )
  const planContract = computed(() => {
    const value = latestPlanEvent.value?.payload.coordination_contract
    return typeof value === 'string' ? value : ''
  })

  const agentEvents = computed(() => state.events.filter((event) => event.agent_id))
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
    refreshConfiguration,
    refreshDeepSeekBalance,
    refreshDeepSeekUsage,
  }
}
