<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ConversationTurn, MemoryCompactionRecord, PlanTask, RunEvent } from '../types'

const props = defineProps<{
  tasks: PlanTask[]
  events: RunEvent[]
  contract: string
  turns: ConversationTurn[]
  memoryCompactions: MemoryCompactionRecord[]
  visible: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

// Zoom and pan state
const scale = ref(1)
const panX = ref(0)
const panY = ref(0)
const isDragging = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)
const panStartX = ref(0)
const panStartY = ref(0)
const selectedNodeId = ref<string | null>(null)

// Layout constants
const nodeW = 140
const nodeH = 56
const convW = 120
const convH = 32
const memW = 96
const memH = 24
const hGap = 80
const vGap = 56
const padX = 24
const padY = 24
const convLaneW = 150

interface LayoutNode {
  id: string
  type: 'start' | 'conversation' | 'plan' | 'task' | 'memory' | 'synthesis'
  label: string
  sub: string
  x: number
  y: number
  w: number
  h: number
  status: string
  task?: PlanTask
  turn?: ConversationTurn
  memory?: MemoryCompactionRecord
  depth: number
  expandable: boolean
  // Enhanced input/output info
  taskInput?: { objective: string; depends_on: string[]; write_scope: string[] }
  taskOutput?: { summary: string; changed_files: string[]; provides: string[]; error: string | null }
}

const agentEventTypes = new Set([
  'agent.started', 'agent.message', 'tool.started', 'skill.loaded',
  'agent.completed', 'agent.failed',
])

function taskEvents(taskId: string) {
  return props.events.filter((e) => e.task_id === taskId && agentEventTypes.has(e.type))
}

function taskStatus(taskId: string): 'pending' | 'running' | 'completed' | 'failed' {
  const evs = taskEvents(taskId)
  if (evs.some((e) => e.type === 'agent.failed')) return 'failed'
  if (evs.some((e) => e.type === 'agent.completed')) return 'completed'
  if (evs.some((e) => e.type === 'agent.started')) return 'running'
  return 'pending'
}

function taskSummary(taskId: string): { summary: string; changed_files: string[]; provides: string[]; error: string | null } {
  const evs = taskEvents(taskId)
  const completed = evs.find(e => e.type === 'agent.completed')
  const failed = evs.find(e => e.type === 'agent.failed')
  return {
    summary: String(completed?.payload.summary || failed?.payload.summary || ''),
    changed_files: (completed?.payload.changed_files as string[]) || [],
    provides: (completed?.payload.provides as string[]) || [],
    error: failed ? String(failed.payload.error || failed.payload.summary || '') : null,
  }
}

const statusColor: Record<string, string> = {
  pending: '#636366', running: '#0a84ff', completed: '#30d158', failed: '#ff453a',
}

const statusIcon: Record<string, string> = {
  pending: '○', running: '◉', completed: '✓', failed: '✕',
}

const layout = computed(() => {
  const nodes: LayoutNode[] = []
  const edges: { from: string; to: string; label?: string }[] = []

  const tasks = props.tasks.filter(t => !t.agent?.includes('brain'))
  const turns = props.turns
  const compactions = props.memoryCompactions

  if (!tasks.length && !turns.length) {
    return { nodes: [] as LayoutNode[], edges: [] as { from: string; to: string }[], width: 400, height: 100 }
  }

  // --- Conversation lane (left side, vertical) ---
  let convY = padY
  let lastConvNodeId: string | null = null

  turns.forEach((turn, i) => {
    const nodeId = `conv-${turn.id}`
    const userNodeId = `${nodeId}-user`

    nodes.push({
      id: userNodeId, type: 'conversation',
      label: `👤 用户消息 · 第${i + 1}轮`,
      sub: turn.userMessage.slice(0, 40) + (turn.userMessage.length > 40 ? '…' : ''),
      x: padX, y: convY,
      w: convW, h: convH,
      status: 'completed', turn, depth: i, expandable: true,
      taskInput: { objective: turn.userMessage, depends_on: [], write_scope: [] },
      taskOutput: turn.brainResponse ? { summary: turn.brainResponse, changed_files: [], provides: [], error: null } : undefined,
    })
    convY += convH + 6

    if (turn.brainResponse || turn.status !== 'complete') {
      const brainNodeId = `${nodeId}-brain`
      nodes.push({
        id: brainNodeId, type: 'conversation',
        label: turn.status === 'thinking' ? '🧠 思考中…' : '🧠 主脑响应',
        sub: turn.brainResponse
          ? turn.brainResponse.slice(0, 40) + (turn.brainResponse.length > 40 ? '…' : '')
          : turn.status === 'thinking' ? '规划中' : '执行中',
        x: padX, y: convY,
        w: convW, h: convH,
        status: turn.status === 'complete' ? 'completed' : turn.status === 'error' ? 'failed' : 'running',
        turn, depth: i, expandable: true,
      })
      edges.push({ from: userNodeId, to: brainNodeId })
      lastConvNodeId = brainNodeId
      convY += convH + 6
    } else {
      lastConvNodeId = userNodeId
    }

    convY += 8
  })

  const convLaneBottom = convY

  if (!tasks.length) {
    const width = convLaneW + padX * 2
    const height = Math.max(convLaneBottom + padY, 120)
    return { nodes, edges, width, height }
  }

  const taskStartX = convLaneW + padX
  const taskMap = new Map(tasks.map((t) => [t.id, t]))
  const depths = new Map<string, number>()

  function getDepth(id: string): number {
    if (depths.has(id)) return depths.get(id)!
    const t = taskMap.get(id)
    if (!t || !t.depends_on.length) { depths.set(id, 0); return 0 }
    const d = Math.max(...t.depends_on.map(getDepth)) + 1
    depths.set(id, d)
    return d
  }
  tasks.forEach((t) => getDepth(t.id))

  const layers = new Map<number, PlanTask[]>()
  let maxDepth = 0
  tasks.forEach((t) => {
    const d = depths.get(t.id) || 0
    if (!layers.has(d)) layers.set(d, [])
    layers.get(d)!.push(t)
    if (d > maxDepth) maxDepth = d
  })

  const maxPerLayer = Math.max(...Array.from(layers.values()).map(l => l.length), 1)

  // Start node "主脑规划"
  const startId = '__start__'
  const startX = taskStartX
  const startY = padY + (maxPerLayer / 2) * vGap - vGap / 2
  nodes.push({
    id: startId, type: 'start',
    label: '◇ 主脑规划', sub: `${tasks.length} 个任务`,
    x: startX, y: startY,
    w: nodeW, h: nodeH,
    status: 'completed', depth: -1, expandable: false,
  })

  // Connect last conversation → start
  if (lastConvNodeId) {
    edges.push({ from: lastConvNodeId, to: startId, label: '生成 DAG' })
  }

  // Task nodes
  const outputTaskIds = new Set<string>()

  tasks.forEach((t) => {
    const rawDepth = depths.get(t.id) || 0
    const d = rawDepth + 1
    const layerTasks = layers.get(rawDepth) || []
    const idx = layerTasks.indexOf(t)
    const layerCount = layerTasks.length
    const yOff = layerCount === 1 ? 0 : (idx - (layerCount - 1) / 2) * vGap

    const tStatus = taskStatus(t.id)
    const output = taskSummary(t.id)
    if (output.provides?.length) {
      output.provides.forEach(p => outputTaskIds.add(p))
    }

    const inputLabels: string[] = []
    if (t.depends_on.length) {
      t.depends_on.forEach(depId => {
        const depTask = taskMap.get(depId)
        if (depTask) inputLabels.push(depTask.title)
      })
    }

    const nodeId = t.id
    nodes.push({
      id: nodeId, type: 'task',
      label: t.title, sub: `${t.agent}`,
      x: startX + d * (nodeW + hGap),
      y: padY + (maxPerLayer / 2) * vGap + yOff - vGap / 2,
      w: nodeW, h: nodeH,
      status: tStatus, task: t,
      depth: d, expandable: true,
      taskInput: {
        objective: t.objective,
        depends_on: inputLabels,
        write_scope: t.write_scope,
      },
      taskOutput: output,
    })

    if (t.depends_on.length) {
      t.depends_on.forEach((depId) => edges.push({ from: depId, to: nodeId }))
    } else {
      edges.push({ from: startId, to: nodeId })
    }
  })

  // Memory compaction nodes
  compactions.forEach((mem, i) => {
    const memId = `mem-${i}`
    const memX = taskStartX + (mem.wave) * (nodeW + hGap) - hGap / 2
    const memY = padY + (maxPerLayer / 2) * vGap + vGap / 2 + 16
    nodes.push({
      id: memId, type: 'memory',
      label: `Wave ${mem.wave} 压缩`,
      sub: mem.tokenCountBefore && mem.tokenCountAfter
        ? `${mem.tokenCountBefore.toLocaleString()}→${mem.tokenCountAfter.toLocaleString()} tokens`
        : mem.agentsCompacted.join(', '),
      x: memX, y: memY,
      w: memW, h: memH,
      status: 'completed', memory: mem,
      depth: mem.wave, expandable: true,
    })
  })

  // Synthesis node
  const endId = '__synthesis__'
  const endDepth = maxDepth + 2
  const synX = taskStartX + endDepth * (nodeW + hGap)
  const finishEvents = props.events.filter(e =>
    ['run.summary', 'run.completed', 'brain.synthesizing'].includes(e.type),
  )
  const synStatus = finishEvents.length > 0 ? 'completed'
    : (props.events.some(e => e.type === 'agent.completed') ? 'running' : 'pending')

  nodes.push({
    id: endId, type: 'synthesis',
    label: '◆ 结果汇总',
    sub: finishEvents.length
      ? `${taskMap.size} 任务完成`
      : props.events.some(e => e.type === 'agent.completed') ? '执行中…' : '等待',
    x: synX, y: startY,
    w: nodeW, h: nodeH,
    status: synStatus, depth: endDepth, expandable: true,
  })

  // Connect leaf tasks → synthesis
  tasks.forEach((t) => {
    const isLeaf = !tasks.some((other) => other.depends_on.includes(t.id))
    if (isLeaf) edges.push({ from: t.id, to: endId })
  })

  const width = padX * 2 + convLaneW + (endDepth + 1) * (nodeW + hGap) + nodeW + padX
  const height = Math.max(padY * 2 + maxPerLayer * vGap + 120, convLaneBottom + padY)

  return { nodes, edges, width, height }
})

function getEdgePath(edge: { from: string; to: string }): string {
  const fromNd = layout.value.nodes.find(n => n.id === edge.from)
  const toNd = layout.value.nodes.find(n => n.id === edge.to)
  if (!fromNd || !toNd) return ''
  const x1 = fromNd.x + fromNd.w
  const y1 = fromNd.y + fromNd.h / 2
  const x2 = toNd.x
  const y2 = toNd.y + toNd.h / 2
  const mx = (x1 + x2) / 2
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`
}

function edgeStrokeColor(edge: { from: string; to: string }): string {
  const fromNd = layout.value.nodes.find(n => n.id === edge.from)
  const toNd = layout.value.nodes.find(n => n.id === edge.to)
  if (fromNd?.type === 'conversation' || toNd?.type === 'conversation') return '#0a84ff'
  if (fromNd?.type === 'memory' || toNd?.type === 'memory') return '#f0a245'
  return '#636366'
}

function nodeFill(node: LayoutNode): string {
  switch (node.type) {
    case 'conversation': return 'rgba(10,132,255,0.08)'
    case 'memory': return 'rgba(242,160,69,0.08)'
    case 'synthesis': return node.status === 'completed' ? 'rgba(48,209,88,0.1)' : 'rgba(48,209,88,0.04)'
    case 'start': return 'rgba(10,132,255,0.1)'
    default: return statusColor[node.status] + '15'
  }
}

function nodeStroke(node: LayoutNode): string {
  switch (node.type) {
    case 'conversation': return '#0a84ff'
    case 'memory': return '#f0a245'
    case 'synthesis': return '#30d158'
    case 'start': return '#0a84ff'
    default: return statusColor[node.status]
  }
}

// Zoom handling
function onWheel(e: WheelEvent) {
  e.preventDefault()
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  const newScale = Math.min(2.0, Math.max(0.5, scale.value * delta))
  // Zoom toward cursor position
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const cx = e.clientX - rect.left
  const cy = e.clientY - rect.top
  const ratio = newScale / scale.value
  panX.value = cx - ratio * (cx - panX.value)
  panY.value = cy - ratio * (cy - panY.value)
  scale.value = newScale
}

function onMousedown(e: MouseEvent) {
  if (e.button !== 0) return
  isDragging.value = true
  dragStartX.value = e.clientX
  dragStartY.value = e.clientY
  panStartX.value = panX.value
  panStartY.value = panY.value
}

function onMousemove(e: MouseEvent) {
  if (!isDragging.value) return
  panX.value = panStartX.value + (e.clientX - dragStartX.value)
  panY.value = panStartY.value + (e.clientY - dragStartY.value)
}

function onMouseup() {
  isDragging.value = false
}

function resetView() {
  scale.value = 1
  panX.value = 0
  panY.value = 0
}

// Keyboard: ESC to close
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close')
  } else if (e.key === '0') {
    resetView()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

// Close on backdrop click
function onBackdropClick(e: MouseEvent) {
  if ((e.target as HTMLElement).classList.contains('dag-modal-backdrop')) {
    emit('close')
  }
}

// Format time
function formatTime(ts: string): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="dag-modal-backdrop"
      @mousedown="onBackdropClick"
    >
      <div class="dag-modal" @wheel="onWheel">
        <!-- Header -->
        <div class="dag-modal-header">
          <div class="dag-modal-title">
            <span class="eyebrow">◇ 任务流程图</span>
            <span class="dag-modal-stats">
              {{ turns.length }} 轮对话 ·
              {{ tasks.length }} 任务 ·
              {{ memoryCompactions.length }} 压缩 ·
              {{ layout.edges.length }} 依赖
            </span>
          </div>
          <div class="dag-modal-actions">
            <ElButton size="small" class="dag-btn" @click="resetView" title="重置视图 (0)">⟲ 重置</ElButton>
            <span class="zoom-label">{{ Math.round(scale * 100) }}%</span>
            <ElButton size="small" class="dag-btn" @click="emit('close')" title="关闭 (Esc)">✕ 关闭</ElButton>
          </div>
        </div>

        <!-- Legend -->
        <div class="dag-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#0a84ff" /> 对话</span>
          <span class="legend-item"><span class="legend-dot" style="background:#636366" /> 等待</span>
          <span class="legend-item"><span class="legend-dot" style="background:#0a84ff" /> 执行中</span>
          <span class="legend-item"><span class="legend-dot" style="background:#30d158" /> 完成</span>
          <span class="legend-item"><span class="legend-dot" style="background:#ff453a" /> 失败</span>
          <span class="legend-item"><span class="legend-dot" style="background:#f0a245" /> 记忆压缩</span>
          <span class="legend-hint">滚轮缩放 · 拖拽平移 · 点击节点展开 · Esc关闭</span>
        </div>

        <!-- SVG Graph -->
        <div
          class="dag-svg-container"
          @mousedown="onMousedown"
          @mousemove="onMousemove"
          @mouseup="onMouseup"
          @mouseleave="onMouseup"
          :style="{ cursor: isDragging ? 'grabbing' : 'grab' }"
        >
          <svg
            :viewBox="`0 0 ${layout.width} ${layout.height}`"
            preserveAspectRatio="xMidYMid meet"
            :style="{
              width: layout.width * scale + 'px',
              height: layout.height * scale + 'px',
              transform: `translate(${panX}px, ${panY}px)`,
            }"
          >
            <defs>
              <marker id="dagm-arrow" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="#636366" />
              </marker>
              <marker id="dagm-arrow-conv" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                <polygon points="0 0, 8 3, 0 6" fill="#0a84ff" />
              </marker>
              <marker id="dagm-arrow-green" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="#30d158" />
              </marker>
              <marker id="dagm-arrow-orange" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="#f0a245" />
              </marker>
              <!-- Drop shadow -->
              <filter id="dagm-shadow">
                <feDropShadow dx="0" dy="1" stdDeviation="2" flood-opacity="0.15" />
              </filter>
            </defs>

            <!-- Edges -->
            <g>
              <path
                v-for="(edge, i) in layout.edges"
                :key="'e' + i"
                :d="getEdgePath(edge)"
                :stroke="edgeStrokeColor(edge)"
                stroke-width="2"
                fill="none"
                :marker-end="
                  edgeStrokeColor(edge) === '#30d158' ? 'url(#dagm-arrow-green)' :
                  edgeStrokeColor(edge) === '#f0a245' ? 'url(#dagm-arrow-orange)' :
                  edgeStrokeColor(edge) === '#0a84ff' ? 'url(#dagm-arrow-conv)' :
                  'url(#dagm-arrow)'
                "
                opacity="0.7"
              />
            </g>

            <!-- Nodes -->
            <g
              v-for="node in layout.nodes"
              :key="node.id"
              :transform="`translate(${node.x},${node.y})`"
              class="dagm-node"
              :class="{
                selected: selectedNodeId === node.id,
                running: node.status === 'running',
              }"
              @click.stop="node.expandable ? selectedNodeId = selectedNodeId === node.id ? null : node.id : null"
              :style="{ cursor: node.expandable ? 'pointer' : 'default' }"
            >
              <!-- Node background -->
              <rect
                :width="node.w" :height="node.h"
                rx="10" ry="10"
                :fill="nodeFill(node)"
                :stroke="nodeStroke(node)"
                stroke-width="1.5"
                :filter="selectedNodeId === node.id ? 'url(#dagm-shadow)' : undefined"
              />

              <!-- Status indicator -->
              <circle
                :cx="10" :cy="node.h / 2" r="5"
                :fill="statusColor[node.status]"
                :class="node.status === 'running' ? 'pulse' : ''"
              />

              <!-- Node type icon -->
              <text
                :x="22" :y="node.h / 2 - 8"
                font-size="10" font-weight="700" :fill="nodeStroke(node)"
              >
                {{ node.label.length > 16 ? node.label.slice(0, 16) + '…' : node.label }}
              </text>
              <text
                :x="22" :y="node.h / 2 + 7"
                font-size="8" fill="var(--secondary)"
              >
                {{ node.sub.length > 24 ? node.sub.slice(0, 24) + '…' : node.sub }}
              </text>

              <!-- Expanded detail panel -->
              <g v-if="selectedNodeId === node.id && node.expandable">
                <!-- Task expanded detail -->
                <template v-if="node.type === 'task' && node.task">
                  <rect
                    :x="0" :y="node.h + 6" :width="Math.max(node.w * 2.2, 300)" height="220"
                    rx="8" ry="8"
                    fill="var(--surface)" stroke="var(--separator-soft)" stroke-width="1"
                    filter="url(#dagm-shadow)"
                  />
                  <!-- Input section -->
                  <text :x="12" :y="node.h + 24" font-size="10" font-weight="700" fill="#64d2ff">输入</text>
                  <rect :x="12" :y="node.h + 30" :width="Math.max(node.w * 2.2, 300) - 24" height="1" fill="var(--separator-soft)" />
                  <text :x="12" :y="node.h + 50" font-size="9" fill="var(--secondary)">目标：</text>
                  <text :x="12" :y="node.h + 65" font-size="8" fill="var(--label)">
                    <tspan v-for="(line, li) in node.taskInput?.objective.match(/.{1,50}/g) || []" :key="li" :x="12" :dy="li === 0 ? 0 : 13">{{ line }}</tspan>
                  </text>
                  <text v-if="node.taskInput?.depends_on.length" :x="12" :y="node.h + 95" font-size="9" fill="var(--secondary)">
                    依赖：{{ node.taskInput.depends_on.join(', ') }}
                  </text>
                  <text v-if="node.taskInput?.write_scope.length" :x="12" :y="node.h + 110" font-size="9" fill="var(--secondary)">
                    写范围：{{ node.taskInput.write_scope.join(', ') }}
                  </text>

                  <!-- Output section -->
                  <text :x="12" :y="node.h + 136" font-size="10" font-weight="700" fill="#30d158">输出</text>
                  <rect :x="12" :y="node.h + 142" :width="Math.max(node.w * 2.2, 300) - 24" height="1" fill="var(--separator-soft)" />
                  <text :x="12" :y="node.h + 162" font-size="9" :fill="node.status === 'failed' ? 'var(--red)' : 'var(--secondary)'">
                    {{ node.taskOutput?.error ? '错误：' : '结果：' }}
                  </text>
                  <text :x="12" :y="node.h + 177" font-size="8" :fill="node.status === 'failed' ? '#ff6961' : 'var(--label)'">
                    {{ (node.taskOutput?.error || node.taskOutput?.summary || '进行中…').slice(0, 120) }}
                  </text>
                  <text v-if="node.taskOutput?.changed_files.length" :x="12" :y="node.h + 200" font-size="8" fill="var(--tertiary)">
                    修改文件：{{ node.taskOutput.changed_files.slice(0, 5).join(', ') }}{{ node.taskOutput.changed_files.length > 5 ? ` +${node.taskOutput.changed_files.length - 5}` : '' }}
                  </text>
                  <text v-if="node.taskOutput?.provides.length" :x="12" :y="node.h + 215" font-size="8" fill="var(--secondary)">
                    提供：{{ node.taskOutput.provides.join(', ').slice(0, 80) }}
                  </text>
                </template>

                <!-- Conversation expanded detail -->
                <template v-if="node.type === 'conversation' && node.turn">
                  <rect
                    :x="0" :y="node.h + 6" :width="320" height="110"
                    rx="8" ry="8"
                    fill="var(--surface)" stroke="var(--separator-soft)" stroke-width="1"
                    filter="url(#dagm-shadow)"
                  />
                  <text :x="12" :y="node.h + 24" font-size="10" font-weight="700" fill="#64d2ff">用户消息</text>
                  <text :x="12" :y="node.h + 44" font-size="8" fill="var(--label)" style="white-space: pre-wrap;">
                    {{ node.turn.userMessage.slice(0, 200) }}{{ node.turn.userMessage.length > 200 ? '…' : '' }}
                  </text>
                  <text :x="12" :y="node.h + 70" font-size="10" font-weight="700" fill="#30d158">主脑响应</text>
                  <text :x="12" :y="node.h + 90" font-size="8" fill="var(--label)">
                    {{ (node.turn.brainResponse || '等待中…').slice(0, 200) }}{{ (node.turn.brainResponse || '').length > 200 ? '…' : '' }}
                  </text>
                </template>

                <!-- Synthesis expanded detail -->
                <template v-if="node.type === 'synthesis'">
                  <rect
                    :x="0" :y="node.h + 6" :width="280" height="80"
                    rx="8" ry="8"
                    fill="var(--surface)" stroke="var(--separator-soft)" stroke-width="1"
                    filter="url(#dagm-shadow)"
                  />
                  <text :x="12" :y="node.h + 24" font-size="10" font-weight="700" fill="#30d158">执行结果汇总</text>
                  <text :x="12" :y="node.h + 46" font-size="9" fill="var(--label)">
                    {{ tasks.length }} 个任务
                    · {{ tasks.filter(t => taskStatus(t.id) === 'completed').length }} 完成
                    · {{ tasks.filter(t => taskStatus(t.id) === 'failed').length }} 失败
                  </text>
                  <text :x="12" :y="node.h + 66" font-size="8" fill="var(--secondary)">
                    汇总来自所有叶子任务的结果，生成最终回答
                  </text>
                </template>
              </g>
            </g>
          </svg>
        </div>

        <!-- Contract -->
        <ElCollapse v-if="contract" class="dag-contract">
          <ElCollapseItem title="共享接口 / 协议契约" name="contract">
            <pre>{{ contract }}</pre>
          </ElCollapseItem>
        </ElCollapse>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dag-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.dag-modal {
  width: 95vw;
  height: 92vh;
  background: var(--chrome);
  border: 1px solid var(--separator);
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dag-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--separator-soft);
  flex-shrink: 0;
}

.dag-modal-title {
  display: flex;
  align-items: baseline;
  gap: 14px;
}

.dag-modal-stats {
  font-size: var(--ui-font-xs);
  color: var(--tertiary);
}

.dag-modal-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dag-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  border: 1px solid var(--separator-soft);
  border-radius: 8px;
  background: var(--surface);
  color: var(--secondary);
  font-size: var(--ui-font-xs);
  font-weight: 550;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.dag-btn:hover {
  background: var(--surface-hover);
  color: var(--label);
}

.zoom-label {
  font-size: var(--ui-font-xs);
  color: var(--tertiary);
  font-variant-numeric: tabular-nums;
  min-width: 40px;
  text-align: center;
}

.dag-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  padding: 10px 20px;
  font-size: var(--ui-font-xs);
  color: var(--tertiary);
  border-bottom: 1px solid var(--separator-soft);
  flex-shrink: 0;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.legend-hint {
  margin-left: auto;
  font-style: italic;
  opacity: 0.7;
  font-size: var(--ui-font-xs);
}

.dag-svg-container {
  flex: 1;
  overflow: hidden;
  padding: 12px;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
}

.dag-svg-container svg {
  display: block;
  transition: transform 0.05s ease-out;
}

.dagm-node {
  transition: filter 0.15s;
}

.dagm-node:hover rect {
  stroke-width: 2.2;
}

.dagm-node.selected rect {
  stroke-width: 2.5;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}

.pulse {
  animation: pulse 1.5s ease-in-out infinite;
}

.dag-contract {
  padding: 12px 20px;
  border-top: 1px solid var(--separator-soft);
  flex-shrink: 0;
}

.dag-contract summary {
  color: #64d2ff;
  cursor: pointer;
  font-size: var(--ui-font-xs);
  font-weight: 600;
}

.dag-contract pre {
  max-height: 160px;
  overflow: auto;
  margin: 8px 0 0;
  color: var(--secondary);
  font: var(--ui-font-xs)/1.6 ui-monospace, "SFMono-Regular", Menlo, monospace;
  white-space: pre-wrap;
}
</style>
