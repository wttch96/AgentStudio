<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, onUpdated, ref } from 'vue'
import type { ConversationTurn, MemoryCompactionRecord, PlanTask, RunEvent } from '../types'

const props = defineProps<{
  tasks: PlanTask[]
  events: RunEvent[]
  turns: ConversationTurn[]
  memoryCompactions: MemoryCompactionRecord[]
}>()

const now = ref(Date.now())
const collapsedWaveKeys = ref<Set<string>>(new Set())
const collapsedTaskIds = ref<Set<string>>(new Set())
const collapsedConvIds = ref<Set<string>>(new Set())
let clock: number | undefined
let connectorResizeObserver: ResizeObserver | undefined

interface ConnectorLayout {
  width: number
  railXs: number[]
}

const laneGroupRefs = new Map<number, HTMLElement>()
const connectorLayouts = ref<Record<number, ConnectorLayout>>({})

function measureConnectorLayouts() {
  const next: Record<number, ConnectorLayout> = {}
  for (const [level, group] of laneGroupRefs) {
    if (!group.offsetParent) continue
    const lanes = [...group.querySelectorAll<HTMLElement>(':scope > .agent-lane')]
    const lastLane = lanes.at(-1)
    next[level] = {
      width: Math.max(
        group.clientWidth,
        lastLane ? lastLane.offsetLeft + lastLane.offsetWidth : 0,
      ),
      railXs: lanes.map(lane => lane.offsetLeft + 28),
    }
  }
  if (JSON.stringify(next) !== JSON.stringify(connectorLayouts.value)) {
    connectorLayouts.value = next
  }
}

function setLaneGroupRef(level: number, element: unknown) {
  const previous = laneGroupRefs.get(level)
  if (previous) connectorResizeObserver?.unobserve(previous)
  if (!(element instanceof HTMLElement)) {
    laneGroupRefs.delete(level)
    return
  }
  laneGroupRefs.set(level, element)
  connectorResizeObserver?.observe(element)
  void nextTick(measureConnectorLayouts)
}

function connectorRailX(level: number, index: number) {
  return connectorLayouts.value[level]?.railXs[index] ?? 28
}

function splitConnectorPath(level: number, index: number) {
  const x = connectorRailX(level, index)
  return `M 0 0 V 6 Q 0 14 8 14 H ${x - 8} Q ${x} 14 ${x} 22 V 36`
}

function mergeConnectorPath(level: number, index: number) {
  const x = connectorRailX(level, index)
  return `M ${x} 0 V 6 Q ${x} 14 ${x - 8} 14 H 8 Q 0 14 0 22 V 28`
}

// ==================== Clock ====================
onMounted(() => {
  clock = window.setInterval(() => { now.value = Date.now() }, 1000)
  connectorResizeObserver = new ResizeObserver(measureConnectorLayouts)
  laneGroupRefs.forEach(group => connectorResizeObserver?.observe(group))
  void nextTick(measureConnectorLayouts)
})
onUpdated(measureConnectorLayouts)
onBeforeUnmount(() => {
  window.clearInterval(clock)
  connectorResizeObserver?.disconnect()
})

// ==================== Event filtering ====================
const agentEventTypes = new Set([
  'agent.started', 'agent.message', 'tool.started', 'skill.loaded',
  'agent.retrying', 'agent.completed', 'agent.failed',
])

const timelineEvents = computed(() => {
  const latestPlan = [...props.events]
    .reverse()
    .find(event => event.type === 'plan.created')
  const runId = latestPlan?.run_id || props.events.at(-1)?.run_id
  return runId ? props.events.filter(event => event.run_id === runId) : props.events
})

// ==================== Start events (conversation + plan) ====================
const conversationEntries = computed(() => {
  return props.turns.map((turn) => ({
    type: 'conversation' as const,
    id: turn.id,
    turn,
    timestamp: turn.createdAt,
  }))
})

const startEvents = computed(() =>
  timelineEvents.value.filter((event) =>
    ['run.started', 'workspace.discovery_started', 'planner.started', 'planner.bypassed'].includes(event.type),
  ),
)

const planEvents = computed(() =>
  timelineEvents.value.filter((event) => event.type === 'plan.created'),
)

const decisionEvents = computed(() =>
  timelineEvents.value.filter((event) =>
    ['brain.contract_created'].includes(event.type),
  ),
)

const finishEvents = computed(() =>
  timelineEvents.value.filter((event) =>
    ['brain.synthesizing', 'run.cancel_requested', 'run.completed', 'run.cancelled', 'run.failed', 'run.summary'].includes(event.type),
  ),
)

const planningActive = computed(() => {
  const started = [...timelineEvents.value].reverse().find((event) => event.type === 'planner.started')
  if (!started) return false
  return !timelineEvents.value.some(
    (event) =>
      event.sequence > started.sequence
      && ['plan.created', 'run.failed', 'run.cancelled'].includes(event.type),
  )
})

const hasDiscoveryTasks = computed(() =>
  props.tasks.some((task) => isDiscoveryTask(task)),
)

// ==================== Waves ====================
const waves = computed(() => {
  const byId = new Map(props.tasks.map((task) => [task.id, task]))
  const memo = new Map<string, number>()

  function level(task: PlanTask, visiting = new Set<string>()): number {
    const cached = memo.get(task.id)
    if (cached !== undefined) return cached
    if (visiting.has(task.id)) return 0
    const nextVisiting = new Set(visiting).add(task.id)
    const dependencies = task.depends_on
      .map((id) => byId.get(id))
      .filter((item): item is PlanTask => Boolean(item))
    const value = dependencies.length
      ? Math.max(...dependencies.map((dependency) => level(dependency, nextVisiting))) + 1
      : 0
    memo.set(task.id, value)
    return value
  }

  const grouped = new Map<number, PlanTask[]>()
  for (const task of props.tasks) {
    const taskLevel = level(task)
    grouped.set(taskLevel, [...(grouped.get(taskLevel) ?? []), task])
  }
  return [...grouped.entries()]
    .sort(([left], [right]) => left - right)
    .map(([levelNumber, tasks]) => ({ level: levelNumber, tasks }))
})

// ==================== Helpers ====================
function taskEvents(taskId: string) {
  return timelineEvents.value.filter(
    (event) => event.task_id === taskId && agentEventTypes.has(event.type),
  )
}

function isDiscoveryTask(task: PlanTask) {
  return task.id.startsWith('workspace-discovery-')
}

function waveKey(tasks: PlanTask[]) {
  return tasks.map((task) => task.id).sort().join('|')
}

function isWaveCollapsed(tasks: PlanTask[]) {
  return collapsedWaveKeys.value.has(waveKey(tasks))
}

function toggleWave(tasks: PlanTask[]) {
  const key = waveKey(tasks)
  const next = new Set(collapsedWaveKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedWaveKeys.value = next
}

function isLaneCollapsed(taskId: string) {
  return collapsedTaskIds.value.has(taskId)
}

function toggleLane(taskId: string) {
  const next = new Set(collapsedTaskIds.value)
  if (next.has(taskId)) next.delete(taskId)
  else next.add(taskId)
  collapsedTaskIds.value = next
}

interface TimelineItem {
  key: string
  event: RunEvent
  events: RunEvent[]
}

function groupedTaskEvents(taskId: string): TimelineItem[] {
  const items: TimelineItem[] = []
  for (const event of taskEvents(taskId)) {
    const previous = items.at(-1)
    const tool = event.payload.tool
    const previousTool = previous?.event.payload.tool
    if (
      event.type === 'tool.started'
      && previous?.event.type === 'tool.started'
      && typeof tool === 'string'
      && tool === previousTool
    ) {
      previous.events.push(event)
      previous.key = `${previous.event.sequence}-${event.sequence}`
      continue
    }
    items.push({ key: String(event.sequence), event, events: [event] })
  }
  return items
}

function taskStatus(taskId: string) {
  const events = taskEvents(taskId)
  if (events.some((event) => event.type === 'agent.failed')) return 'failed'
  if (events.some((event) => event.type === 'agent.completed')) return 'completed'
  if (events.some((event) => event.type === 'agent.started')) return 'running'
  return 'pending'
}

function taskTimingText(taskId: string) {
  const events = taskEvents(taskId)
  const status = taskStatus(taskId)
  if (status === 'pending') return ''
  const started = events.find(e => e.type === 'agent.started')
  if (!started) return '--'
  const startedAt = new Date(started.timestamp).getTime()
  if (status === 'completed') {
    const completed = events.find(e => e.type === 'agent.completed')
    if (completed) {
      const duration = ((new Date(completed.timestamp).getTime() - startedAt) / 1000).toFixed(1)
      return `${duration}s`
    }
    return '--'
  }
  if (status === 'failed') {
    const failedEv = events.find(e => e.type === 'agent.failed')
    if (failedEv) {
      const duration = ((new Date(failedEv.timestamp).getTime() - startedAt) / 1000).toFixed(1)
      return `${duration}s · 失败`
    }
    return '--'
  }
  const elapsed = Math.max(0, Math.floor((now.value - startedAt) / 1000))
  return `已运行 ${elapsed}s`
}

function waveStartTime(tasks: PlanTask[]) {
  const timestamps = tasks
    .map(t => {
      const started = taskEvents(t.id).find(e => e.type === 'agent.started')
      return started ? new Date(started.timestamp).getTime() : null
    })
    .filter((t): t is number => t !== null)
  if (timestamps.length === 0) return ''
  return new Date(Math.min(...timestamps)).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function waveStatus(tasks: PlanTask[]) {
  const statuses = tasks.map((task) => taskStatus(task.id))
  if (statuses.some((status) => status === 'failed')) return 'failed'
  if (statuses.every((status) => status === 'completed')) return 'completed'
  if (statuses.some((status) => status === 'running' || status === 'completed')) return 'running'
  return 'pending'
}

function waveSummary(tasks: PlanTask[]) {
  const status = waveStatus(tasks)
  if (status === 'completed') return '本批次结果已汇流'
  if (status === 'failed') return '本批次包含失败节点'
  if (status === 'running') return '等待本批次其他节点完成'
  return '等待本批次节点启动'
}

// Memory compactions for a specific wave
function memoryForWave(waveLevel: number): MemoryCompactionRecord[] {
  return props.memoryCompactions.filter((m) => m.wave === waveLevel + 1)
}

// ==================== Title/Detail/Icon ====================
function title(event: RunEvent) {
  if (event.type === 'plan.created') {
    return event.payload.stage === 'discovery' ? '项目发现 DAG 已生成' : '实施 DAG 已生成'
  }
  const titles: Record<string, string> = {
    'run.started': '运行已启动',
    'workspace.discovery_started': '正在搜索所选工作空间',
    'planner.started': 'DeepSeek 正在规划',
    'planner.bypassed': '已直接选择 Claude Agent',
    'brain.contract_created': 'DeepSeek 已生成共享契约',
    'brain.synthesizing': 'DeepSeek 主脑正在验收',
    'run.summary': '执行结果汇总',
    'run.cancel_requested': '正在取消运行',
    'run.completed': '运行完成',
    'run.cancelled': '运行已取消',
    'run.failed': '运行失败',
  }
  return titles[event.type] ?? event.type
}

function detail(event: RunEvent) {
  const payload = event.payload
  if (event.type === 'planner.started' && planningActive.value) {
    const elapsed = Math.max(0, Math.floor((now.value - new Date(event.timestamp).getTime()) / 1000))
    return `已等待 ${elapsed} 秒 · 正在理解目标…`
  }
  if (event.type === 'planner.bypassed') return '已跳过 DeepSeek 规划'
  if (event.type === 'workspace.discovery_started') return '专业 Agent 将搜索与目标相关的项目'
  if (event.type === 'brain.contract_created') return '前端、后端实施节点将共享同一份接口定义'
  if (event.type === 'agent.retrying') {
    const attempt = Number(payload.attempt || 1)
    return `第 ${attempt} 次恢复 · 从原会话继续，不会重跑节点`
  }
  if (['run.completed', 'run.cancelled'].includes(event.type)) return ''
  if (typeof payload.text === 'string') return payload.text
  if (typeof payload.summary === 'string') return payload.summary
  if (typeof payload.error === 'string') return payload.error
  if (event.type === 'plan.created') {
    const tasks = (payload.tasks as PlanTask[] | undefined) ?? []
    return `${tasks.length} 个任务已排入执行图`
  }
  return ''
}

function icon(event: RunEvent) {
  if (event.type === 'agent.retrying') return '↻'
  if (event.type.includes('tool')) return '⌘'
  if (event.type.includes('skill')) return '◆'
  if (event.type.includes('failed')) return '!'
  if (event.type.includes('completed')) return '✓'
  if (event.type.includes('plan') || event.type.includes('brain') || event.type === 'run.summary') return '◇'
  if (event.type.includes('started')) return '›'
  return '·'
}

function itemTitle(item: TimelineItem) {
  if (item.event.type === 'agent.retrying') return '连接中断，正在恢复会话'
  if (item.event.type === 'tool.started') {
    const tool = typeof item.event.payload.tool === 'string' ? item.event.payload.tool : '工具'
    const base = item.events.length > 1 ? `调用 ${tool} ×${item.events.length}` : `调用 ${tool}`
    let totalBytes = 0
    for (const e of item.events) {
      totalBytes += JSON.stringify(e.payload?.input ?? '').length
    }
    const sizeStr = totalBytes > 1024 ? `${(totalBytes / 1024).toFixed(1)}KB` : `${totalBytes}B`
    return `${base} · 入参 ${sizeStr}`
  }
  if (item.event.type === 'agent.message') {
    const text = typeof item.event.payload?.text === 'string' ? item.event.payload.text : ''
    const bytes = new Blob([text]).size
    const sizeStr = bytes > 1024 ? `${(bytes / 1024).toFixed(1)}KB` : `${bytes}B`
    return `Agent 输出 · ${sizeStr}`
  }
  return title(item.event)
}

function itemSequence(item: TimelineItem) {
  const first = item.events[0].sequence
  const last = item.events.at(-1)?.sequence ?? first
  return first === last ? `#${first}` : `#${first}–#${last}`
}

function failureReason(event: RunEvent) {
  const error = event.payload.error
  if (typeof error === 'string' && error.trim()) {
    if (error.includes('Claude Code returned an error result: success') && event.task_id) {
      const apiErrorEvent = [...taskEvents(event.task_id)].reverse().find(
        candidate => candidate.type === 'agent.message'
          && String(candidate.payload.text || '').trim().toLowerCase().startsWith('api error:'),
      )
      if (apiErrorEvent) return String(apiErrorEvent.payload.text)
    }
    return error
  }
  const summary = event.payload.summary
  if (typeof summary === 'string' && summary.trim()) return summary
  return '执行器没有返回进一步的错误信息。'
}

function failureCategory(event: RunEvent) {
  const reason = failureReason(event).toLowerCase()
  if (reason.includes('max_turn') || reason.includes('最大交互轮次')) return '交互轮次耗尽'
  if (reason.includes('timeout') || reason.includes('超时')) return '执行超时'
  if (
    reason.includes('connection closed')
    || reason.includes('mid-response')
    || reason.includes('请求中断')
    || reason.includes('upstream')
  ) return '模型连接中断'
  if (reason.includes('permission') || reason.includes('权限')) return '工具权限失败'
  if (reason.includes('auth') || reason.includes('鉴权')) return '模型鉴权失败'
  return 'Agent 执行错误'
}

function convIcon(isUser: boolean) {
  return isUser ? '&#x1F464;' : '&#x1F9E0;'
}

function convLabel(isUser: boolean) {
  return isUser ? '用户消息' : '主脑响应'
}
</script>

<template>
  <section class="thinking-timeline" aria-live="polite">
    <div class="section-title">
      <span class="eyebrow">思考流程</span>
      <span>{{ tasks.length ? `${waves.length} 个调度批次` : '等待任务图' }}</span>
    </div>

    <div class="timeline-content">
    <!-- ============ Phase 1: 对话节点 ============ -->
    <div v-if="turns.length" class="flow-phase">
      <div class="phase-divider">
        <span class="phase-mark">&#x1F4AC;</span>
        <span class="phase-label">对话记录</span>
      </div>
      <div class="flow-start">
        <article
          v-for="turn in turns"
          :key="turn.id"
          class="orchestrator-event conv-entry"
          :class="{ collapsed: collapsedConvIds.has(turn.id) }"
        >
          <div class="flow-event-icon conv-icon" aria-hidden="true" v-html="convIcon(true)" />
          <div>
            <strong>{{ turn.userMessage.slice(0, 80) }}{{ turn.userMessage.length > 80 ? '…' : '' }}</strong>
            <p v-if="turn.thinkingText">
              {{ turn.thinkingText.split('\n')[0].slice(0, 100) }}
            </p>
            <div v-if="!collapsedConvIds.has(turn.id) && turn.brainResponse" class="conv-response-preview">
              <span class="conv-resp-label">主脑响应:</span>
              <p>{{ turn.brainResponse.slice(0, 200) }}{{ turn.brainResponse.length > 200 ? '…' : '' }}</p>
            </div>
          </div>
          <div class="conv-actions">
            <span class="conv-seq">{{ new Date(turn.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</span>
            <ElButton
              text
              circle
              class="conv-toggle-btn"
              @click="collapsedConvIds.has(turn.id) ? collapsedConvIds.delete(turn.id) : collapsedConvIds.add(turn.id); collapsedConvIds = new Set(collapsedConvIds)"
              :title="collapsedConvIds.has(turn.id) ? '展开' : '折叠'"
            >
              {{ collapsedConvIds.has(turn.id) ? '⌄' : '⌃' }}
            </ElButton>
          </div>
        </article>
      </div>
    </div>

    <!-- ============ Phase 2: 规划启动 ============ -->
    <div class="flow-start">
      <article
        v-for="event in startEvents"
        :key="event.sequence"
        class="orchestrator-event"
        :class="{ 'planning-active': event.type === 'planner.started' && planningActive }"
      >
        <div class="flow-event-icon" aria-hidden="true">{{ icon(event) }}</div>
        <div>
          <strong>{{ title(event) }}</strong>
          <p v-if="detail(event)">{{ detail(event) }}</p>
          <div v-if="event.type === 'planner.started' && planningActive" class="planning-progress" aria-hidden="true">
            <i />
          </div>
        </div>
        <span>#{{ event.sequence }}</span>
      </article>
    </div>

    <!-- ============ Phase 3: 计划节点 ============ -->
    <div v-for="event in planEvents" :key="event.sequence" class="flow-start">
      <article class="orchestrator-event">
        <div class="flow-event-icon" aria-hidden="true">{{ icon(event) }}</div>
        <div>
          <strong>{{ title(event) }}</strong>
          <p v-if="detail(event)">{{ detail(event) }}</p>
        </div>
        <span>#{{ event.sequence }}</span>
      </article>
    </div>

    <!-- 共享契约 -->
    <div v-if="decisionEvents.length" class="flow-decision">
      <article
        v-for="event in decisionEvents"
        :key="event.sequence"
        class="orchestrator-event"
      >
        <div class="flow-event-icon" aria-hidden="true">{{ icon(event) }}</div>
        <div>
          <strong>{{ title(event) }}</strong>
          <p v-if="detail(event)">{{ detail(event) }}</p>
        </div>
        <span>#{{ event.sequence }}</span>
      </article>
    </div>

    <!-- ============ Phase 4: 执行波浪 + 记忆压缩 ============ -->
    <div
      v-for="wave in waves"
      :key="wave.level"
      class="parallel-wave"
      :class="wave.tasks.length > 1 ? 'is-concurrent' : 'is-serial'"
    >
      <!-- Wave start -->
      <div class="flow-junction split-junction">
        <span class="junction-symbol" aria-hidden="true">⑂</span>
        <div class="junction-copy">
          <strong>LangGraph 第 {{ wave.level + 1 }} 轮{{ wave.tasks.length > 1 ? '并发分流' : '执行' }}</strong>
          <small>
            {{ wave.tasks.length }} 个节点{{ wave.tasks.length > 1 ? '并行执行' : '开始执行' }}
            <template v-if="waveStartTime(wave.tasks)"> · {{ waveStartTime(wave.tasks) }}</template>
          </small>
        </div>
        <ElButton
          size="small"
          :aria-expanded="!isWaveCollapsed(wave.tasks)"
          @click="toggleWave(wave.tasks)"
        >
          <span aria-hidden="true">{{ isWaveCollapsed(wave.tasks) ? '⌄' : '⌃' }}</span>
          <span>{{ isWaveCollapsed(wave.tasks) ? '展开' : '折叠' }}</span>
        </ElButton>
      </div>

      <!-- Agent lanes -->
      <div
        v-show="!isWaveCollapsed(wave.tasks)"
        class="agent-lanes"
        :ref="element => setLaneGroupRef(wave.level, element)"
      >
        <svg
          v-if="wave.tasks.length > 1 && connectorLayouts[wave.level]"
          class="parallel-connectors split-connectors"
          :width="connectorLayouts[wave.level].width"
          height="36"
          aria-hidden="true"
        >
          <path
            v-for="(_, index) in wave.tasks"
            :key="`split-${index}`"
            :d="splitConnectorPath(wave.level, index)"
          />
        </svg>
        <svg
          v-if="wave.tasks.length > 1 && connectorLayouts[wave.level]"
          class="parallel-connectors merge-connectors"
          :width="connectorLayouts[wave.level].width"
          height="28"
          aria-hidden="true"
        >
          <path
            v-for="(_, index) in wave.tasks"
            :key="`merge-${index}`"
            :d="mergeConnectorPath(wave.level, index)"
          />
        </svg>
        <article
          v-for="task in wave.tasks"
          :key="task.id"
          class="agent-lane"
          :class="[taskStatus(task.id), { collapsed: isLaneCollapsed(task.id) }]"
        >
          <header class="lane-header">
            <span class="lane-avatar">{{ task.agent.charAt(0).toUpperCase() }}</span>
            <div class="lane-header-copy">
              <strong>{{ task.agent }}</strong>
              <small>{{ task.title }}</small>
              <small v-if="taskTimingText(task.id)" class="lane-timing">{{ taskTimingText(task.id) }}</small>
            </div>
            <div class="lane-actions">
              <span class="lane-status">{{ taskStatus(task.id) }}</span>
              <ElButton
                text
                circle
                class="lane-collapse-button"
                :aria-expanded="!isLaneCollapsed(task.id)"
                @click="toggleLane(task.id)"
              >
                {{ isLaneCollapsed(task.id) ? '⌄' : '⌃' }}
              </ElButton>
            </div>
          </header>

          <!-- Task input params -->
          <div v-show="!isLaneCollapsed(task.id)" class="task-params">
            <div class="param-row">
              <span class="param-label">目标:</span>
              <span class="param-value">{{ task.objective.slice(0, 200) }}{{ task.objective.length > 200 ? '…' : '' }}</span>
            </div>
            <div v-if="task.write_scope.length" class="param-row">
              <span class="param-label">写范围:</span>
              <span class="param-value">{{ task.write_scope.join(', ') }}</span>
            </div>
            <div v-if="task.depends_on.length" class="param-row">
              <span class="param-label">依赖:</span>
              <span class="param-value">{{ task.depends_on.join(', ') }}</span>
            </div>
          </div>

          <!-- Lane events -->
          <div
            v-show="!isLaneCollapsed(task.id)"
            class="lane-events"
          >
            <article v-for="item in groupedTaskEvents(task.id)" :key="item.key" class="lane-event">
              <div class="lane-event-marker" :class="item.event.type.replace('.', '-')" aria-hidden="true">
                {{ icon(item.event) }}
              </div>
              <div class="lane-event-body">
                <div>
                  <strong>{{ itemTitle(item) }}</strong>
                  <span>{{ itemSequence(item) }}</span>
                </div>
                <p v-if="!['tool.started', 'agent.failed'].includes(item.event.type) && detail(item.event)">
                  {{ detail(item.event) }}
                </p>
                <div v-if="item.event.type === 'agent.failed'" class="agent-failure-detail">
                  <div>
                    <strong>{{ failureCategory(item.event) }}</strong>
                    <span>{{ item.event.payload.summary ?? '节点未能完成' }}</span>
                  </div>
                  <pre>{{ failureReason(item.event) }}</pre>
                </div>
                <ElCollapse v-if="item.event.type === 'tool.started'" class="tool-call-details">
                  <ElCollapseItem :title="`查看 ${item.events.length} 次调用参数`" :name="item.event.sequence">
                  <div class="tool-call-list">
                    <section v-for="(call, index) in item.events" :key="call.sequence">
                      <span>第 {{ index + 1 }} 次 · #{{ call.sequence }}</span>
                      <pre>{{ JSON.stringify(call.payload.input ?? {}, null, 2).slice(0, 400) }}{{ JSON.stringify(call.payload.input ?? {}).length > 400 ? '\n…(截断)' : '' }}</pre>
                    </section>
                  </div>
                  </ElCollapseItem>
                </ElCollapse>
              </div>
            </article>
            <div v-if="taskEvents(task.id).length === 0" class="lane-waiting">
              <span /> 等待调度器启动
            </div>
          </div>
        </article>
      </div>

      <!-- Wave merge -->
      <div class="flow-junction merge-junction" :class="waveStatus(wave.tasks)">
        <span class="junction-symbol" aria-hidden="true">⌄</span>
        <div>
          <strong>{{ wave.tasks.length > 1 ? '并发结果汇流' : '节点执行结束' }}</strong>
          <small>{{ waveSummary(wave.tasks) }}</small>
        </div>
      </div>

      <!-- Memory compaction for this wave -->
      <div v-if="memoryForWave(wave.level).length" class="memory-compaction-entry">
        <span class="memory-dot" aria-hidden="true">&#x1F9E0;</span>
        <div>
          <strong>记忆压缩 · Wave {{ wave.level + 1 }}</strong>
          <small>
            <template v-for="(mem, i) in memoryForWave(wave.level)" :key="i">
              {{ mem.agentsCompacted.join(', ') }}
              <template v-if="mem.tokenCountBefore && mem.tokenCountAfter">
                ({{ mem.tokenCountBefore.toLocaleString() }} → {{ mem.tokenCountAfter.toLocaleString() }} tokens,
                {{ ((1 - mem.tokenCountAfter / mem.tokenCountBefore) * 100).toFixed(0) }}% 压缩)
              </template>
              {{ i < memoryForWave(wave.level).length - 1 ? ' · ' : '' }}
            </template>
          </small>
        </div>
      </div>

      <!-- Discovery → replan transition -->
      <div
        v-if="wave.tasks.some(isDiscoveryTask) && decisionEvents.length"
        class="flow-decision"
      >
        <article
          v-for="event in decisionEvents"
          :key="event.sequence"
          class="orchestrator-event"
        >
          <div class="flow-event-icon" aria-hidden="true">{{ icon(event) }}</div>
          <div>
            <strong>{{ title(event) }}</strong>
            <p v-if="detail(event)">{{ detail(event) }}</p>
          </div>
          <span>#{{ event.sequence }}</span>
        </article>
      </div>
    </div>

    <!-- ============ Phase 5: 综合汇总 + 记忆提取 ============ -->
    <div v-if="finishEvents.length" class="flow-finish">
      <article
        v-for="event in finishEvents"
        :key="event.sequence"
        class="orchestrator-event"
        :class="{
          'run-failure-detail': event.type === 'run.failed',
          'synthesis-entry': event.type === 'run.summary' || event.type === 'brain.synthesizing',
        }"
      >
        <div class="flow-event-icon" aria-hidden="true">{{ icon(event) }}</div>
        <div>
          <strong>{{ title(event) }}</strong>
          <p v-if="detail(event)">{{ detail(event) }}</p>
          <div v-if="event.type === 'run.summary' && event.payload.result_count !== undefined" class="result-stats">
            {{ event.payload.result_count }} 个执行结果已汇流
          </div>
        </div>
        <span>#{{ event.sequence }}</span>
      </article>
    </div>

    <!-- Memory extraction -->
    <div v-if="timelineEvents.some(e => e.type === 'memory.extracted')" class="memory-extraction-entry">
      <span class="memory-extract-icon" aria-hidden="true">&#x1F4BE;</span>
      <div>
        <strong>长期记忆已保存</strong>
        <small>LangMem 从本次会话提取了关键信息供后续使用</small>
      </div>
    </div>
    </div>
  </section>
</template>

<style scoped>
.thinking-timeline {
  position: relative;
  margin-bottom: 1rem;
  padding: 0 12px 12px 0;
}

.timeline-content {
  position: relative;
  min-height: 24px;
}

.timeline-content::before {
  position: absolute;
  z-index: 0;
  top: 0;
  bottom: 20px;
  left: 34px;
  width: 2px;
  border-radius: 2px;
  background: rgba(100, 210, 255, .48);
  content: "";
  pointer-events: none;
}

.section-title {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.5rem;
  color: var(--secondary);
  font-size: var(--ui-font-xs);
}

/* Phase divider */
.flow-phase {
  margin-bottom: 0.25rem;
}

.phase-divider {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0 0.35rem 8px;
}

.phase-mark {
  font-size: var(--ui-font-lg);
}

.phase-label {
  font-size: var(--ui-font-xs);
  font-weight: 650;
  color: var(--label);
}

/* Conversation entries */
.conv-entry {
  margin-left: 0;
  padding-left: 40px;
}

.conv-icon {
  background: rgba(10, 132, 255, 0.12) !important;
  color: #64d2ff !important;
}

.conv-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.conv-seq {
  color: var(--tertiary);
  font-size: var(--ui-font-xs);
}

.conv-toggle-btn {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 6px;
  background: rgba(118, 118, 128, 0.15);
  color: var(--secondary);
  cursor: pointer;
  font-size: var(--ui-font-xs);
  line-height: 1;
}

.conv-toggle-btn:hover {
  background: rgba(118, 118, 128, 0.28);
  color: var(--label);
}

.conv-response-preview {
  margin-top: 0.35rem;
  padding: 0.35rem 0.5rem;
  background: var(--surface);
  border-radius: 6px;
  border: 1px solid var(--separator-soft);
}

.conv-resp-label {
  font-size: var(--ui-font-xs);
  color: var(--green);
  font-weight: 600;
}

.conv-response-preview p {
  margin: 0.2rem 0 0;
  font-size: var(--ui-font-xs);
  color: var(--secondary);
  line-height: 1.4;
}

/* Task params in lane */
.task-params {
  position: relative;
  z-index: 1;
  padding: 0.4rem 0.75rem 0.4rem 44px;
  background: rgba(0, 0, 0, 0.15);
  border-bottom: 1px solid var(--separator-soft);
}

.param-row {
  display: flex;
  gap: 0.4rem;
  margin-bottom: 0.2rem;
  font-size: var(--ui-font-xs);
  line-height: 1.4;
}

.param-row:last-child {
  margin-bottom: 0;
}

.param-label {
  flex-shrink: 0;
  color: var(--tertiary);
  font-weight: 600;
}

.param-value {
  color: var(--secondary);
  word-break: break-word;
}

/* Memory compaction entry */
.memory-compaction-entry {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  margin: 0.5rem 0 0.5rem 40px;
  padding: 0.5rem 0.7rem;
  border-radius: 8px;
  border: 1px solid rgba(191, 90, 242, 0.18);
  background: rgba(191, 90, 242, 0.06);
}

.memory-dot {
  font-size: var(--ui-font-md);
  flex-shrink: 0;
  margin-top: 1px;
}

.memory-compaction-entry strong {
  font-size: var(--ui-font-xs);
  font-weight: 600;
  color: var(--label);
  display: block;
}

.memory-compaction-entry small {
  font-size: var(--ui-font-xs);
  color: var(--secondary);
  display: block;
  margin-top: 0.15rem;
}

/* Memory extraction entry */
.memory-extraction-entry {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  margin: 0.5rem 0 0.5rem 40px;
  padding: 0.5rem 0.7rem;
  border-radius: 8px;
  border: 1px solid rgba(48, 209, 88, 0.18);
  background: rgba(48, 209, 88, 0.06);
}

.memory-extract-icon {
  font-size: var(--ui-font-md);
  flex-shrink: 0;
}

.memory-extraction-entry strong {
  font-size: var(--ui-font-xs);
  font-weight: 600;
  color: var(--label);
  display: block;
}

.memory-extraction-entry small {
  font-size: var(--ui-font-xs);
  color: var(--secondary);
  display: block;
  margin-top: 0.15rem;
}

/* Synthesis highlight */
.synthesis-entry {
  border-left: 0;
}

.result-stats {
  font-size: var(--ui-font-xs);
  color: var(--green);
  margin-top: 0.25rem;
}

/* Reuse core timeline styles from main.css via global selectors */
</style>

<!-- Global styles for event timeline elements (needed since scoped styles don't apply to dynamic classes from main.css) -->
<style>
/* Reuse existing timeline styles */
.thinking-timeline .flow-start,
.thinking-timeline .flow-decision,
.thinking-timeline .flow-finish {
  position: relative;
  padding-left: 40px;
}

.thinking-timeline .flow-start::before,
.thinking-timeline .flow-decision::before,
.thinking-timeline .flow-finish::before {
  content: none;
}

.thinking-timeline .flow-finish::before {
  bottom: 15px;
}

.thinking-timeline .orchestrator-event {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  min-height: 44px;
  padding: 8px 0 14px 16px;
}

.thinking-timeline .orchestrator-event::before {
  content: none;
}

.thinking-timeline .orchestrator-event::after {
  content: none;
}

.thinking-timeline .flow-event-icon {
  position: absolute;
  top: 7px;
  left: -17px;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--blue-soft);
  color: #64d2ff;
  font-size: var(--ui-font-xs);
  font-weight: 650;
  box-shadow: 0 0 0 1px rgba(10,132,255,.3), 0 0 0 3px var(--background, #000);
}

.thinking-timeline .orchestrator-event strong {
  font-size: var(--ui-font-xs);
  font-weight: 600;
}

.thinking-timeline .orchestrator-event > span {
  color: var(--tertiary);
  font-size: var(--ui-font-xs);
}

.thinking-timeline .orchestrator-event p {
  margin: 5px 0 0;
  color: var(--secondary);
  font-size: var(--ui-font-xs);
  line-height: 1.55;
  white-space: pre-wrap;
}

.thinking-timeline .planning-active {
  margin: 3px 0 12px;
  padding: 12px 14px;
  border: 1px solid rgba(10,132,255,.2);
  border-radius: 12px;
  background: rgba(10,132,255,.08);
}

.thinking-timeline .planning-progress {
  position: relative;
  height: 3px;
  margin-top: 10px;
  overflow: hidden;
  border-radius: 2px;
  background: rgba(10,132,255,.18);
  border: 1px solid rgba(10,132,255,.12);
}

.thinking-timeline .planning-progress i {
  position: absolute;
  width: 34%;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, #64d2ff, transparent);
  animation: planner-progress 1.7s ease-in-out infinite;
}

@keyframes planner-progress {
  from { left: -34%; }
  to { left: 100%; }
}

.thinking-timeline .run-failure-detail {
  margin: 4px 0 10px;
  padding: 11px 13px;
  border: 1px solid rgba(255,69,58,.25);
  border-radius: 11px;
  background: rgba(255,69,58,.08);
}

.thinking-timeline .parallel-wave {
  position: relative;
  padding: 4px 0 0;
}

.thinking-timeline .flow-junction {
  position: relative;
  display: flex;
  width: max-content;
  max-width: calc(100% - 40px);
  min-height: 42px;
  margin-left: 52px;
  align-items: center;
  gap: 10px;
}

.thinking-timeline .flow-junction::before {
  content: none;
}

.thinking-timeline .flow-junction::after {
  content: none;
}

.thinking-timeline .junction-symbol {
  position: relative;
  z-index: 1;
  margin-left: -29px;
  box-shadow:
    inset 0 0 0 1px rgba(191,90,242,.30),
    0 0 0 3px var(--background, #000);
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  background: rgba(191,90,242,.14);
  color: #da8fff;
  font-size: var(--ui-font-xs);
}

.thinking-timeline .flow-junction .junction-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.thinking-timeline .flow-junction strong {
  font-size: var(--ui-font-xs);
  font-weight: 620;
}

.thinking-timeline .flow-junction small {
  color: var(--tertiary);
  font-size: var(--ui-font-xs);
}

.thinking-timeline .agent-lanes {
  position: relative;
  display: grid;
  grid-auto-columns: minmax(220px, 1fr);
  grid-auto-flow: column;
  align-items: start;
  gap: 10px;
  overflow-x: auto;
  margin-left: 14px;
  padding: 24px 0 20px 48px;
  scrollbar-width: thin;
}

.thinking-timeline .is-serial .agent-lanes {
  grid-auto-flow: row;
  grid-template-columns: minmax(0, 1fr);
  margin-left: 8px;
  padding: 4px 0 12px;
  overflow: visible;
}

.thinking-timeline .is-concurrent .agent-lanes {
  align-items: stretch;
  margin-left: 35px;
  padding: 36px 0 28px 18px;
}

.thinking-timeline .parallel-connectors {
  position: absolute;
  left: 0;
  z-index: 0;
  overflow: visible;
  pointer-events: none;
}

.thinking-timeline .split-connectors {
  top: 0;
  height: 36px;
}

.thinking-timeline .merge-connectors {
  bottom: 0;
  height: 28px;
}

.thinking-timeline .parallel-connectors path {
  fill: none;
  stroke: rgba(100, 210, 255, .5);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}

.thinking-timeline .agent-lane {
  position: relative;
  z-index: 1;
  min-width: 220px;
  overflow: hidden;
  border: 1px solid var(--separator-soft);
  border-radius: 14px;
  background: rgba(28,28,30,.92);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
}

.thinking-timeline .is-concurrent .agent-lane {
  height: 100%;
}

.thinking-timeline .agent-lane::before {
  content: none;
}

.thinking-timeline .agent-lane::after {
  position: absolute;
  z-index: 4;
  top: 26px;
  bottom: 0;
  left: 27px;
  width: 2px;
  border-radius: 2px;
  background: rgba(100, 210, 255, .30);
  content: "";
  pointer-events: none;
}

.thinking-timeline .agent-lane.running {
  border-color: rgba(10,132,255,.52);
  box-shadow: 0 0 0 3px rgba(10,132,255,.07), inset 0 1px 0 rgba(255,255,255,.05);
}

.thinking-timeline .agent-lane.completed {
  border-color: rgba(48,209,88,.25);
}

.thinking-timeline .agent-lane.failed {
  border-color: rgba(255,69,58,.48);
}

.thinking-timeline .lane-header {
  position: relative;
  z-index: 3;
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 12px;
  border-bottom: 1px solid var(--separator-soft);
  background: rgba(44,44,46,.52);
}

.thinking-timeline .lane-avatar {
  position: relative;
  z-index: 5;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: linear-gradient(145deg,#48484a,#2c2c2e);
  color: var(--label);
  font-size: var(--ui-font-xs);
  font-weight: 650;
}

.thinking-timeline .agent-lane.running .lane-avatar {
  background: linear-gradient(145deg,#2997ff,#0071e3);
}

.thinking-timeline .lane-header-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.thinking-timeline .lane-header strong {
  overflow: hidden;
  font-size: var(--ui-font-xs);
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thinking-timeline .lane-header small {
  overflow: hidden;
  color: var(--secondary);
  font-size: var(--ui-font-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thinking-timeline .lane-header small.lane-timing {
  color: var(--blue);
  font-variant-numeric: tabular-nums;
}

.thinking-timeline .lane-actions {
  display: flex;
  align-items: center;
  gap: 5px;
}

.thinking-timeline .lane-status {
  border-radius: 6px;
  padding: 3px 5px;
  background: rgba(118,118,128,.18);
  color: var(--tertiary);
  font-size: var(--ui-font-xs);
  text-transform: uppercase;
}

.thinking-timeline .lane-collapse-button {
  display: grid;
  place-items: center;
  width: 23px;
  height: 23px;
  border: 0;
  border-radius: 7px;
  background: rgba(118,118,128,.15);
  color: var(--secondary);
  cursor: pointer;
  font-size: var(--ui-font-xs);
  line-height: 1;
}

.thinking-timeline .lane-collapse-button:hover {
  background: rgba(118,118,128,.28);
  color: var(--label);
}

.thinking-timeline .agent-lane.running .lane-status {
  background: var(--blue-soft);
  color: #64d2ff;
}

.thinking-timeline .agent-lane.completed .lane-status {
  background: rgba(48,209,88,.12);
  color: var(--green);
}

.thinking-timeline .agent-lane.failed .lane-status {
  background: rgba(255,69,58,.12);
  color: var(--red);
}

.thinking-timeline .lane-events {
  position: relative;
  min-height: 90px;
  max-height: 420px;
  overflow-y: auto;
  padding: 12px 12px 12px 17px;
}

.thinking-timeline .lane-events::before {
  content: none;
}

.thinking-timeline .lane-event {
  position: relative;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  padding-bottom: 13px;
}

.thinking-timeline .lane-event:last-child {
  padding-bottom: 0;
}

.thinking-timeline .lane-event-marker {
  z-index: 5;
  display: grid;
  place-items: center;
  width: 21px;
  height: 21px;
  border-radius: 50%;
  background: var(--surface-raised, #242426);
  color: var(--secondary);
  font-size: var(--ui-font-xs);
  box-shadow: 0 0 0 2px var(--surface-raised, #242426), 0 0 0 3px rgba(100, 210, 255, .22);
}

.thinking-timeline .lane-event-marker.agent-completed {
  background: rgba(48,209,88,.14);
  color: var(--green);
}

.thinking-timeline .lane-event-marker.agent-failed {
  background: rgba(255,69,58,.14);
  color: var(--red);
}

.thinking-timeline .lane-event-body {
  min-width: 0;
  padding-top: 2px;
}

.thinking-timeline .lane-event-body > div {
  display: flex;
  justify-content: space-between;
  gap: 7px;
}

.thinking-timeline .lane-event-body strong {
  font-size: var(--ui-font-xs);
  font-weight: 600;
}

.thinking-timeline .lane-event-body span {
  color: var(--tertiary);
  font-size: var(--ui-font-xs);
}

.thinking-timeline .lane-event-body p {
  display: -webkit-box;
  overflow: hidden;
  margin: 4px 0 0;
  color: var(--secondary);
  font-size: var(--ui-font-xs);
  line-height: 1.5;
  white-space: pre-wrap;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 6;
}

.thinking-timeline .lane-event-body details {
  margin-top: 5px;
  color: var(--secondary);
  font-size: var(--ui-font-xs);
}

.thinking-timeline .lane-event-body summary {
  cursor: pointer;
  color: #64d2ff;
}

.thinking-timeline .lane-event-body pre,
.thinking-timeline .agent-failure-detail pre {
  overflow-x: auto;
  margin: 7px 0 0;
  padding: 9px;
  border-radius: 8px;
  background: #111113;
  color: rgba(235,235,245,.76);
  font: var(--ui-font-xs)/1.55 ui-monospace,"SFMono-Regular",Menlo,monospace;
  white-space: pre-wrap;
}

.thinking-timeline .agent-failure-detail {
  display: block;
  margin-top: 7px;
  padding: 9px;
  border: 1px solid rgba(255,69,58,.22);
  border-radius: 9px;
  background: rgba(255,69,58,.08);
}

.thinking-timeline .agent-failure-detail > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.thinking-timeline .agent-failure-detail > div strong {
  color: #ff6961;
}

.thinking-timeline .agent-failure-detail > div span {
  overflow: hidden;
  color: var(--secondary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thinking-timeline .agent-failure-detail pre {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid rgba(255,69,58,.12);
  color: #ffb4ae;
}

.thinking-timeline .tool-call-list section {
  margin-bottom: 0.5rem;
}

.thinking-timeline .tool-call-list section:last-child {
  margin-bottom: 0;
}

.thinking-timeline .tool-call-list span {
  font-size: var(--ui-font-xs);
  color: var(--tertiary);
}

.thinking-timeline .lane-waiting {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  color: var(--tertiary);
  font-size: var(--ui-font-xs);
}

.thinking-timeline .lane-waiting span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--tertiary);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}
</style>
