import { computed, ComputedRef } from 'vue'
import type { Run, RunEvent, ConversationTurn, ActiveAgent, PlanTask, MemoryCompactionRecord } from '../types'

/**
 * 从 useWorkspace 提取的派生状态逻辑。
 * 负责从原始事件构建 ConversationTurn[]、ActiveAgent[] 和 MemoryCompactionRecord[]。
 */
export function useRunTimeline(
  conversationRuns: ComputedRef<Run[]>,
  conversationEvents: ComputedRef<RunEvent[]>,
  activeRunEvents: ComputedRef<RunEvent[]>,
  activeRun: ComputedRef<Run | null>,
) {
  /**
   * 从 conversation 级别事件重建对话轮次
   */
  const conversationTurns = computed<ConversationTurn[]>(() => {
    const runs = conversationRuns.value.length
      ? conversationRuns.value
      : activeRun.value
        ? [activeRun.value]
        : []
    const events = conversationEvents.value.length
      ? conversationEvents.value
      : activeRunEvents.value

    const eventsByRun = new Map<string, RunEvent[]>()
    for (const e of events) {
      const list = eventsByRun.get(e.run_id) || []
      list.push(e)
      eventsByRun.set(e.run_id, list)
    }

    return runs.map((run) => {
      const runEvents = eventsByRun.get(run.id) || []
      const sorted = [...runEvents].sort((a, b) => a.sequence - b.sequence)

      const planEvent = sorted.find((e) => e.type === 'plan.created')
      const planTasks: PlanTask[] = (planEvent?.payload.tasks as PlanTask[] | undefined) ?? []

      // 构建思考文本
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
      for (const e of sorted) {
        if (e.type === 'agent.message' && typeof e.payload?.text === 'string') {
          const txt = (e.payload.text as string).slice(0, 500)
          if (txt.trim()) thinkingParts.push(`[${e.agent_id || 'agent'}]: ${txt}`)
        }
      }
      const thinkingText = thinkingParts.length ? thinkingParts.join('\n') : null

      // 脑响应
      const summaryEvent = sorted.find((e) => e.type === 'run.summary')
      const brainSynthesizing = sorted.find((e) => e.type === 'brain.synthesizing')
      const planSummary = (planEvent?.payload.summary as string) || ''
      const brainResponse =
        run.final_answer ||
        (summaryEvent?.payload.text as string) ||
        (brainSynthesizing?.payload.text as string) ||
        planSummary ||
        null

      // 记忆压缩事件
      const memoryEvents: MemoryCompactionRecord[] = sorted
        .filter((e) => e.type === 'memory.compacted')
        .map((e) => ({
          wave: (e.payload.wave as number) || 0,
          agentsCompacted:
            (e.payload.agents as string[]) || (e.payload.agent ? [e.payload.agent as string] : []),
          tokenCountBefore: (e.payload.token_count_before as number) || null,
          tokenCountAfter: (e.payload.token_count_after as number) || null,
          timestamp: e.timestamp,
        }))

      // 波次数
      const waveEvents = sorted.filter((e) => e.type === 'wave.started')
      const waveCount = waveEvents.length

      // 状态
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
  })

  /**
   * 活跃 Agent 列表
   */
  const activeAgents = computed<ActiveAgent[]>(() => {
    const events =
      conversationEvents.value.length ? conversationEvents.value : activeRunEvents.value
    const planTurns = conversationTurns.value
    const allPlanTasks = planTurns.flatMap((t) => t.planTasks)

    const started = new Map<string, { taskId: string; title: string; startedAt: string }>()
    const completed = new Set<string>()
    const failed = new Set<string>()

    for (const e of events) {
      if (e.type === 'agent.started' && e.agent_id) {
        started.set(e.agent_id, {
          taskId: e.task_id || '',
          title:
            (e.payload.title as string) ||
            allPlanTasks.find((t) => t.id === e.task_id)?.title ||
            '',
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
  })

  /**
   * 记忆压缩记录
   */
  const memoryCompactions = computed<MemoryCompactionRecord[]>(() => {
    const events =
      conversationEvents.value.length ? conversationEvents.value : activeRunEvents.value
    return events
      .filter((e) => e.type === 'memory.compacted')
      .map((e) => ({
        wave: (e.payload.wave as number) || 0,
        agentsCompacted:
          (e.payload.agents as string[]) || (e.payload.agent ? [e.payload.agent as string] : []),
        tokenCountBefore: (e.payload.token_count_before as number) || null,
        tokenCountAfter: (e.payload.token_count_after as number) || null,
        timestamp: e.timestamp,
      }))
  })

  /**
   * 最新的 plan.created 事件
   */
  const latestPlanEvent = computed(() =>
    [...conversationEvents.value, ...activeRunEvents.value]
      .reverse()
      .find((item) => item.type === 'plan.created'),
  )

  const planTasks = computed<PlanTask[]>(
    () => (latestPlanEvent.value?.payload.tasks as PlanTask[] | undefined) ?? [],
  )

  const planContract = computed(() => {
    const value = latestPlanEvent.value?.payload.coordination_contract
    return typeof value === 'string' ? value : ''
  })

  return {
    conversationTurns,
    activeAgents,
    memoryCompactions,
    planTasks,
    planContract,
  }
}
