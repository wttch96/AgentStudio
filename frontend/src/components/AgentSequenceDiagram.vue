<script setup lang="ts">
import { computed } from 'vue'
import type { PlanTask, RunEvent } from '../types'

const props = defineProps<{ tasks: PlanTask[]; events: RunEvent[] }>()

const laneNames = computed(() => {
  const agents = [...new Set(props.tasks.map(task => task.agent).filter(Boolean))]
  return [...new Set(['用户', '主脑', ...agents, 'Reviewer'])]
})
const laneX = computed(() => new Map(laneNames.value.map((name, index) => [name, 90 + index * 180])))

interface Message {
  from: string
  to: string
  label: string
  time: number
  status: string
  group: string
  phase: 'dispatch' | 'return' | 'control'
}

const taskWaves = computed(() => {
  const byId = new Map(props.tasks.map(task => [task.id, task]))
  const memo = new Map<string, number>()
  function depth(taskId: string, visiting = new Set<string>()): number {
    if (memo.has(taskId)) return memo.get(taskId)!
    if (visiting.has(taskId)) return 0
    const task = byId.get(taskId)
    const next = new Set(visiting).add(taskId)
    const dependencies = (task?.depends_on || []).filter(id => byId.has(id))
    const result = dependencies.length
      ? Math.max(...dependencies.map(id => depth(id, next))) + 1
      : 0
    memo.set(taskId, result)
    return result
  }
  for (const task of props.tasks) depth(task.id)
  return memo
})

const scopedEvents = computed(() => {
  const latestPlan = [...props.events]
    .reverse()
    .find(event => event.type === 'plan.created')
  const runId = latestPlan?.run_id || props.events.at(-1)?.run_id
  return runId ? props.events.filter(event => event.run_id === runId) : props.events
})

const messages = computed<Message[]>(() => {
  const result: Message[] = []
  for (const event of scopedEvents.value) {
    const time = Date.parse(event.timestamp || '') || event.sequence
    if (event.type === 'run.started') result.push({
      from: '用户', to: '主脑', label: '提交目标', time, status: '',
      group: `control-${event.sequence}`, phase: 'control',
    })
    if (event.type === 'agent.started' && event.agent_id) {
      const wave = taskWaves.value.get(event.task_id || '') ?? event.sequence
      result.push({
        from: '主脑', to: event.agent_id, label: event.task_id || '委派任务',
        time, status: 'running', group: `wave-${wave}-dispatch`, phase: 'dispatch',
      })
    }
    if ((event.type === 'agent.completed' || event.type === 'agent.failed') && event.agent_id) {
      const wave = taskWaves.value.get(event.task_id || '') ?? event.sequence
      result.push({
        from: event.agent_id, to: 'Reviewer', label: event.task_id || '返回结果',
        time, status: event.type.endsWith('failed') ? 'failed' : 'completed',
        group: `wave-${wave}-return`, phase: 'return',
      })
    }
    if (event.type === 'review.completed') result.push({
      from: 'Reviewer', to: '主脑', label: '验收结果', time, status: '',
      group: `control-${event.sequence}`, phase: 'control',
    })
    if (event.type === 'run.summary') result.push({
      from: '主脑', to: '用户', label: '最终汇总', time, status: 'completed',
      group: `control-${event.sequence}`, phase: 'control',
    })
  }
  return result.sort((a, b) => a.time - b.time)
})

const sequenceLayout = computed(() => {
  const grouped = new Map<string, Message[]>()
  for (const message of messages.value) {
    const items = grouped.get(message.group) || []
    items.push(message)
    grouped.set(message.group, items)
  }

  const rows: Array<{ message: Message; y: number }> = []
  const bands: Array<{ group: string; count: number; y: number; height: number }> = []
  let cursor = 92
  for (const [group, groupMessages] of grouped) {
    const isConcurrent = group.startsWith('wave-') && groupMessages.length > 1
    const rowGap = isConcurrent ? 34 : 0
    groupMessages.forEach((message, index) => {
      rows.push({ message, y: cursor + index * rowGap })
    })
    if (isConcurrent) {
      bands.push({
        group,
        count: groupMessages.length,
        y: cursor - 24,
        height: 42 + (groupMessages.length - 1) * rowGap,
      })
    }
    cursor += isConcurrent
      ? 68 + (groupMessages.length - 1) * rowGap
      : 68
  }
  return { rows, bands, height: Math.max(360, cursor + 48) }
})

const width = computed(() => Math.max(720, laneNames.value.length * 180))
const height = computed(() => sequenceLayout.value.height)
function color(status: string) {
  return status === 'failed' ? '#ff453a' : status === 'completed' ? '#30d158' : '#0a84ff'
}
function marker(status: string) {
  return status === 'failed' ? 'url(#sequence-arrow-failed)'
    : status === 'completed' ? 'url(#sequence-arrow-completed)'
      : 'url(#sequence-arrow-running)'
}
function labelX(message: Message) {
  const from = laneX.value.get(message.from) || 90
  const to = laneX.value.get(message.to) || 90
  if (message.phase === 'dispatch') return to - 10
  if (message.phase === 'return') return from + 10
  return (from + to) / 2
}
function labelAnchor(message: Message) {
  if (message.phase === 'dispatch') return 'end'
  if (message.phase === 'return') return 'start'
  return 'middle'
}
</script>

<template>
  <div class="sequence-wrap">
    <svg :viewBox="`0 0 ${width} ${height}`" :width="width" :height="height" role="img" aria-label="Agent 时序图">
      <defs>
        <marker id="sequence-arrow-running" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#0a84ff" />
        </marker>
        <marker id="sequence-arrow-completed" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#30d158" />
        </marker>
        <marker id="sequence-arrow-failed" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#ff453a" />
        </marker>
      </defs>
      <g v-for="lane in laneNames" :key="lane">
        <rect :x="laneX.get(lane)! - 64" y="16" width="128" height="34" rx="8" class="lane-head" />
        <text :x="laneX.get(lane)" y="38" text-anchor="middle" class="lane-label">{{ lane }}</text>
        <line :x1="laneX.get(lane)" y1="50" :x2="laneX.get(lane)" :y2="height - 24" class="lifeline" />
      </g>
      <g v-for="band in sequenceLayout.bands" :key="band.group">
        <rect x="22" :y="band.y" :width="width - 44" :height="band.height" rx="8" class="concurrent-band" />
        <text x="32" :y="band.y + 15" class="concurrent-label">并发 ×{{ band.count }}</text>
      </g>
      <g v-for="(row, index) in sequenceLayout.rows" :key="`${row.message.time}-${index}`">
        <line
          :x1="laneX.get(row.message.from) || 90"
          :y1="row.y"
          :x2="laneX.get(row.message.to) || 90"
          :y2="row.y"
          :stroke="color(row.message.status)"
          stroke-width="2"
          :marker-end="marker(row.message.status)"
        />
        <text :x="labelX(row.message)" :y="row.y - 7" :text-anchor="labelAnchor(row.message)" class="message-label">
          {{ row.message.label }}
        </text>
      </g>
      <text v-if="!messages.length" :x="width / 2" y="180" text-anchor="middle" class="empty">暂无可展示的 Agent 交互事件</text>
    </svg>
  </div>
</template>

<style scoped>
.sequence-wrap { height: 100%; overflow: auto; background: var(--el-bg-color-page); }
.lane-head { fill: var(--el-bg-color); stroke: var(--el-border-color); }
.lane-label { fill: var(--el-text-color-primary); font-size: var(--ui-font-sm); font-weight: 600; }
.lifeline { stroke: var(--el-border-color); stroke-width: 1; stroke-dasharray: 5 5; }
.message-label { fill: var(--el-text-color-secondary); font-size: var(--ui-font-xs); paint-order: stroke; stroke: var(--el-bg-color-page); stroke-width: 3px; }
.concurrent-band { fill: rgba(10, 132, 255, 0.07); stroke: rgba(10, 132, 255, 0.18); stroke-dasharray: 4 4; }
.concurrent-label { fill: #0a84ff; font-size: var(--ui-font-xs); font-weight: 600; }
.empty { fill: var(--el-text-color-secondary); font-size: var(--ui-font-base); }
</style>
