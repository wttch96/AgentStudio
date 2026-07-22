<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { PlanTask, RunEvent } from '../types'

const props = defineProps<{ tasks: PlanTask[]; events: RunEvent[] }>()
const now = ref(Date.now())
const collapsedTaskIds = ref<Set<string>>(new Set())
const collapsedWaveKeys = ref<Set<string>>(new Set())
let clock: number | undefined

interface TimelineItem {
  key: string
  event: RunEvent
  events: RunEvent[]
}

const agentEventTypes = new Set([
  'agent.started',
  'agent.message',
  'tool.started',
  'skill.loaded',
  'agent.completed',
  'agent.failed',
])

const startEvents = computed(() =>
  props.events.filter((event) =>
    ['run.started', 'planner.started', 'planner.bypassed', 'plan.created'].includes(event.type),
  ),
)

const finishEvents = computed(() =>
  props.events.filter((event) =>
    ['brain.synthesizing', 'run.cancel_requested', 'run.completed', 'run.cancelled', 'run.failed'].includes(event.type),
  ),
)

const planningActive = computed(() => {
  const started = props.events.some((event) => event.type === 'planner.started')
  const finished = props.events.some((event) =>
    ['plan.created', 'run.failed', 'run.cancelled'].includes(event.type),
  )
  return started && !finished
})

onMounted(() => {
  clock = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
})
onBeforeUnmount(() => window.clearInterval(clock))

/**
 * 依据依赖关系计算 LangGraph 执行批次。同一层的任务没有未完成的相互依赖，
 * 因而会被 scheduler 放入同一个 super-step 并行执行。
 */
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

function taskEvents(taskId: string) {
  return props.events.filter(
    (event) => event.task_id === taskId && agentEventTypes.has(event.type),
  )
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

/**
 * 使用本轮任务 ID 生成稳定标识，避免用户切换任务记录后，另一条运行中相同层级的
 * 分流意外继承折叠状态。
 */
function waveKey(tasks: PlanTask[]) {
  return tasks.map((task) => task.id).sort().join('|')
}

function isWaveCollapsed(tasks: PlanTask[]) {
  return collapsedWaveKeys.value.has(waveKey(tasks))
}

/** 一次折叠或展开本轮分流中的全部 Agent 泳道，汇流节点保持可见。 */
function toggleWave(tasks: PlanTask[]) {
  const key = waveKey(tasks)
  const next = new Set(collapsedWaveKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedWaveKeys.value = next
}

/** 将相邻且同名的工具调用折叠成一项，同时保留每次原始事件和参数。 */
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

function title(event: RunEvent) {
  const titles: Record<string, string> = {
    'run.started': '运行已启动',
    'planner.started': 'DeepSeek 正在规划',
    'planner.bypassed': '已直接选择 Claude Agent',
    'plan.created': '任务 DAG 已生成',
    'agent.started': 'Agent 已启动',
    'agent.message': '思考与进展',
    'tool.started': '调用工具',
    'skill.loaded': '加载 Skill',
    'agent.completed': '节点已完成',
    'agent.failed': '节点执行失败',
    'brain.synthesizing': 'DeepSeek 主脑正在验收',
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
    if (elapsed < 15) return `已等待 ${elapsed} 秒 · 正在理解目标并检查工作区结构…`
    if (elapsed < 45) return `已等待 ${elapsed} 秒 · 正在生成并校验任务 DAG，复杂目标可能需要更久…`
    return `已等待 ${elapsed} 秒 · DeepSeek 或模型代理响应较慢，系统仍在等待；你可以继续等待或停止本次运行。`
  }
  if (event.type === 'planner.bypassed') return '已跳过 DeepSeek 规划，直接执行指定 Agent'
  if (['run.completed', 'run.cancelled'].includes(event.type)) return ''
  if (typeof payload.text === 'string') return payload.text
  if (typeof payload.summary === 'string') return payload.summary
  if (typeof payload.error === 'string') return payload.error
  if (typeof payload.title === 'string') return payload.title
  if (typeof payload.tool === 'string') return payload.tool
  if (typeof payload.skill === 'string') return payload.skill
  if (event.type === 'plan.created') {
    return `${(payload.tasks as unknown[] | undefined)?.length ?? 0} 个任务已排入执行图`
  }
  return ''
}

function failureReason(event: RunEvent) {
  const error = event.payload.error
  if (typeof error === 'string' && error.trim()) return error
  const summary = event.payload.summary
  if (typeof summary === 'string' && summary.trim()) return summary
  return '执行器没有返回进一步的错误信息。'
}

function failureCategory(event: RunEvent) {
  const reason = failureReason(event).toLowerCase()
  if (reason.includes('max_turn') || reason.includes('最大交互轮次')) return '交互轮次耗尽'
  if (reason.includes('timeout') || reason.includes('超时') || reason.includes('超过')) return '执行超时'
  if (reason.includes('permission') || reason.includes('权限')) return '工具权限失败'
  if (reason.includes('auth') || reason.includes('鉴权')) return '模型鉴权失败'
  return 'Agent 执行错误'
}

function icon(event: RunEvent) {
  if (event.type.includes('tool')) return '⌘'
  if (event.type.includes('skill')) return '◆'
  if (event.type.includes('failed')) return '!'
  if (event.type.includes('completed')) return '✓'
  if (event.type.includes('plan') || event.type.includes('brain')) return '◇'
  if (event.type.includes('started')) return '›'
  return '·'
}

function itemTitle(item: TimelineItem) {
  if (item.event.type !== 'tool.started') return title(item.event)
  const tool = typeof item.event.payload.tool === 'string' ? item.event.payload.tool : '工具'
  return item.events.length > 1 ? `调用 ${tool} ×${item.events.length}` : `调用 ${tool}`
}

function itemSequence(item: TimelineItem) {
  const first = item.events[0].sequence
  const last = item.events.at(-1)?.sequence ?? first
  return first === last ? `#${first}` : `#${first}–#${last}`
}
</script>

<template>
  <section class="execution-flow" aria-live="polite">
    <div class="section-title">
      <span class="eyebrow">执行时间线</span>
      <span>{{ waves.length ? `${waves.length} 个调度批次` : '等待任务图' }}</span>
    </div>

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

    <div v-for="wave in waves" :key="wave.level" class="parallel-wave">
      <div class="flow-junction split-junction">
        <span class="junction-symbol" aria-hidden="true">⑂</span>
        <div class="junction-copy">
          <strong>LangGraph 第 {{ wave.level + 1 }} 轮分流</strong>
          <small>
            {{ wave.tasks.length }} 个节点{{ wave.tasks.length > 1 ? '并行执行' : '开始执行' }}{{ isWaveCollapsed(wave.tasks) ? ' · 已折叠' : '' }}
          </small>
        </div>
        <button
          class="wave-collapse-button"
          type="button"
          :aria-expanded="!isWaveCollapsed(wave.tasks)"
          :aria-controls="`wave-lanes-${wave.level}`"
          :title="isWaveCollapsed(wave.tasks) ? '展开本轮全部泳道' : '折叠本轮全部泳道'"
          @click="toggleWave(wave.tasks)"
        >
          <span aria-hidden="true">{{ isWaveCollapsed(wave.tasks) ? '⌄' : '⌃' }}</span>
          <span>{{ isWaveCollapsed(wave.tasks) ? '展开' : '折叠' }}</span>
        </button>
      </div>

      <div
        v-show="!isWaveCollapsed(wave.tasks)"
        :id="`wave-lanes-${wave.level}`"
        class="agent-lanes"
      >
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
            </div>
            <div class="lane-actions">
              <span class="lane-status">{{ taskStatus(task.id) }}</span>
              <button
                class="lane-collapse-button"
                type="button"
                :aria-expanded="!isLaneCollapsed(task.id)"
                :aria-controls="`lane-events-${task.id}`"
                :title="isLaneCollapsed(task.id) ? '展开泳道' : '折叠泳道'"
                @click="toggleLane(task.id)"
              >
                {{ isLaneCollapsed(task.id) ? '⌄' : '⌃' }}
              </button>
            </div>
          </header>

          <div
            v-show="!isLaneCollapsed(task.id)"
            :id="`lane-events-${task.id}`"
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
                <p
                  v-if="!['tool.started', 'agent.failed'].includes(item.event.type) && detail(item.event)"
                >
                  {{ detail(item.event) }}
                </p>
                <div v-if="item.event.type === 'agent.failed'" class="agent-failure-detail">
                  <div>
                    <strong>{{ failureCategory(item.event) }}</strong>
                    <span>{{ item.event.payload.summary ?? '节点未能完成' }}</span>
                  </div>
                  <pre>{{ failureReason(item.event) }}</pre>
                </div>
                <details v-if="item.event.type === 'tool.started'" class="tool-call-details">
                  <summary>查看 {{ item.events.length }} 次调用参数</summary>
                  <div class="tool-call-list">
                    <section v-for="(call, index) in item.events" :key="call.sequence">
                      <span>第 {{ index + 1 }} 次 · #{{ call.sequence }}</span>
                      <pre>{{ JSON.stringify(call.payload.input ?? {}, null, 2) }}</pre>
                    </section>
                  </div>
                </details>
              </div>
            </article>
            <div v-if="taskEvents(task.id).length === 0" class="lane-waiting">
              <span /> 等待调度器启动
            </div>
          </div>
        </article>
      </div>

      <div class="flow-junction merge-junction" :class="waveStatus(wave.tasks)">
        <span class="junction-symbol" aria-hidden="true">⌄</span>
        <div>
          <strong>并行结果汇流</strong>
          <small>{{ waveSummary(wave.tasks) }}</small>
        </div>
      </div>
    </div>

    <div v-if="finishEvents.length" class="flow-finish">
      <article
        v-for="event in finishEvents"
        :key="event.sequence"
        class="orchestrator-event"
        :class="{ 'run-failure-detail': event.type === 'run.failed' }"
      >
        <div class="flow-event-icon" aria-hidden="true">{{ icon(event) }}</div>
        <div>
          <strong>{{ title(event) }}</strong>
          <p v-if="detail(event)">{{ detail(event) }}</p>
        </div>
        <span>#{{ event.sequence }}</span>
      </article>
    </div>
  </section>
</template>
