<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ConversationTurn, MemoryCompactionRecord, PlanTask, RunEvent } from '../types'

const props = defineProps<{
  tasks: PlanTask[]
  events: RunEvent[]
  contract: string
  turns: ConversationTurn[]
  memoryCompactions: MemoryCompactionRecord[]
}>()

const expandedId = ref<string | null>(null)
const collapsedConvIds = ref<Set<string>>(new Set())

function toggleNode(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function toggleConv(id: string) {
  const next = new Set(collapsedConvIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedConvIds.value = next
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

function taskSummary(taskId: string): string {
  const completed = taskEvents(taskId).find((e) => e.type === 'agent.completed')
  const failed = taskEvents(taskId).find((e) => e.type === 'agent.failed')
  const msg = completed?.payload.summary || failed?.payload.error || ''
  return typeof msg === 'string' ? msg.slice(0, 120) : ''
}

const statusColor: Record<string, string> = {
  pending: '#636366', running: '#0a84ff', completed: '#30d158', failed: '#ff453a',
}

// ==================== Unified DAG Layout ====================
const nodeW = 108
const nodeH = 34
const convW = 90
const convH = 28
const memW = 80
const memH = 22
const hGap = 65
const vGap = 38
const padX = 10
const padY = 14
const convLaneW = 110 // Width for conversation lane

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
}

const layout = computed(() => {
  const nodes: LayoutNode[] = []
  const edges: { from: string; to: string }[] = []

  const tasks = props.tasks.filter(t => !t.agent?.includes('brain'))
  const turns = props.turns
  const compactions = props.memoryCompactions

  if (!tasks.length && !turns.length) {
    return { nodes: [] as LayoutNode[], edges: [] as { from: string; to: string }[], width: 400, height: 100 }
  }

  // --- Conversation lane (left side, vertical) ---
  let convY = padY
  const convNodeIds: string[] = []

  turns.forEach((turn, i) => {
    const nodeId = `conv-${turn.id}`
    convNodeIds.push(nodeId)

    // User message node
    const userNodeId = `${nodeId}-user`
    nodes.push({
      id: userNodeId,
      type: 'conversation',
      label: turn.userMessage.slice(0, 20) + (turn.userMessage.length > 20 ? '…' : ''),
      sub: '用户消息',
      x: padX,
      y: convY,
      w: convW,
      h: convH,
      status: 'completed',
      turn,
      depth: i,
      expandable: true,
    })
    convY += convH + 8

    // Brain response node (if exists)
    if (turn.brainResponse || turn.status === 'executing' || turn.status === 'thinking') {
      const brainNodeId = `${nodeId}-brain`
      const respStatus = turn.status === 'complete' ? 'completed' : turn.status === 'error' ? 'failed' : 'running'
      nodes.push({
        id: brainNodeId,
        type: 'conversation',
        label: turn.brainResponse
          ? turn.brainResponse.slice(0, 20) + (turn.brainResponse.length > 20 ? '…' : '')
          : turn.status === 'thinking' ? '思考中…' : '执行中…',
        sub: '主脑响应',
        x: padX,
        y: convY,
        w: convW,
        h: convH,
        status: respStatus,
        turn,
        depth: i,
        expandable: true,
      })
      convY += convH + 8
    }

    // Connect user → brain
    if (turn.brainResponse || turn.status === 'executing' || turn.status === 'thinking') {
      edges.push({ from: userNodeId, to: `${nodeId}-brain` })
    }

    convY += 12 // gap between turns
  })

  const convLaneBottom = convY

  // --- Task DAG (right of conversation lane) ---
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

  const maxPerLayer = Math.max(...Array.from(layers.values()).map((l) => l.length), 1)

  // Start node "主脑规划" with connection from last conversation
  const startId = '__start__'
  const startX = taskStartX
  const startY = padY + (maxPerLayer / 2) * vGap - vGap / 2
  nodes.push({
    id: startId, type: 'start',
    label: '主脑规划', sub: tasks.length + ' 个任务',
    x: startX, y: startY,
    w: nodeW, h: nodeH,
    status: 'completed', depth: -1, expandable: false,
  })

  // Connect last conversation node to start
  if (convNodeIds.length > 0) {
    const lastConvId = convNodeIds[convNodeIds.length - 1]
    // Find the last node that was added for this turn
    const convNodes = nodes.filter(n => n.id.startsWith(lastConvId))
    if (convNodes.length > 0) {
      edges.push({ from: convNodes[convNodes.length - 1].id, to: startId })
    }
  }

  // Task nodes
  tasks.forEach((t) => {
    const rawDepth = depths.get(t.id) || 0
    const d = rawDepth + 1
    const layerTasks = layers.get(rawDepth) || []
    const idx = layerTasks.indexOf(t)
    const layerCount = layerTasks.length
    const yOff = layerCount === 1 ? 0 : (idx - (layerCount - 1) / 2) * vGap

    const nodeId = t.id
    nodes.push({
      id: nodeId, type: 'task',
      label: t.title, sub: t.agent,
      x: startX + d * (nodeW + hGap),
      y: padY + (maxPerLayer / 2) * vGap + yOff - vGap / 2,
      w: nodeW, h: nodeH,
      status: taskStatus(t.id), task: t,
      depth: d, expandable: true,
    })

    if (t.depends_on.length) {
      t.depends_on.forEach((depId) => edges.push({ from: depId, to: nodeId }))
    } else {
      edges.push({ from: startId, to: nodeId })
    }
  })

  // Memory compaction nodes between waves
  const endDepth = maxDepth + 2
  compactions.forEach((mem, i) => {
    const memId = `mem-${i}`
    const memX = startX + (mem.wave) * (nodeW + hGap) - hGap / 2
    const memY = padY + (maxPerLayer / 2) * vGap + vGap / 2 + 10
    nodes.push({
      id: memId, type: 'memory',
      label: `Wave ${mem.wave} 压缩`,
      sub: mem.tokenCountBefore && mem.tokenCountAfter
        ? `${mem.tokenCountBefore.toLocaleString()}→${mem.tokenCountAfter.toLocaleString()}`
        : mem.agentsCompacted.join(', '),
      x: memX, y: memY,
      w: memW, h: memH,
      status: 'completed', memory: mem,
      depth: mem.wave, expandable: true,
    })
  })

  // Synthesis node at end
  const endId = '__synthesis__'
  const synX = startX + endDepth * (nodeW + hGap)
  const finishEvents = props.events.filter(e =>
    ['run.summary', 'run.completed', 'brain.synthesizing'].includes(e.type),
  )
  const synStatus = finishEvents.length > 0 ? 'completed' : (props.events.some(e => e.type === 'agent.completed') ? 'running' : 'pending')
  nodes.push({
    id: endId, type: 'synthesis',
    label: '结果汇总', sub: finishEvents.length ? '已生成' : '等待中',
    x: synX, y: startY,
    w: nodeW, h: nodeH,
    status: synStatus, depth: endDepth, expandable: true,
  })

  // Connect all leaf tasks to synthesis
  tasks.forEach((t) => {
    const isLeaf = !tasks.some((other) => other.depends_on.includes(t.id))
    if (isLeaf) edges.push({ from: t.id, to: endId })
  })

  const width = padX * 2 + convLaneW + (endDepth + 1) * (nodeW + hGap) + nodeW
  const height = Math.max(padY * 2 + maxPerLayer * vGap, convLaneBottom + padY)

  return { nodes, edges, width, height }
})

function convIcon(turn: ConversationTurn) {
  return turn.brainResponse ? 'B' : 'U'
}

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

function edgeOpacity(edge: { from: string; to: string }): string {
  const fromNd = layout.value.nodes.find(n => n.id === edge.from)
  return fromNd?.type === 'conversation' ? '0.5' : '0.6'
}

function edgeDashArray(edge: { from: string; to: string }): string | undefined {
  const fromNd = layout.value.nodes.find(n => n.id === edge.from)
  const toNd = layout.value.nodes.find(n => n.id === edge.to)
  if (fromNd?.type === 'memory' || toNd?.type === 'memory') return '4,3'
  return undefined
}

function edgeMarker(edge: { from: string; to: string }): string {
  const fromNd = layout.value.nodes.find(n => n.id === edge.from)
  return fromNd?.type === 'conversation' ? 'url(#dag-arrow-conv)' : 'url(#dag-arrow)'
}

function nodeFillClass(node: LayoutNode) {
  switch (node.type) {
    case 'conversation': return node.status === 'running' ? 'rgba(10,132,255,0.08)' : 'rgba(10,132,255,0.06)'
    case 'memory': return 'rgba(242,160,69,0.08)'
    case 'synthesis': return node.status === 'completed' ? 'rgba(48,209,88,0.08)' : 'rgba(48,209,88,0.04)'
    default: return statusColor[node.status] + '12'
  }
}

function nodeStrokeColor(node: LayoutNode) {
  switch (node.type) {
    case 'conversation': return '#0a84ff'
    case 'memory': return '#f0a245'
    case 'synthesis': return '#30d158'
    case 'start': return '#0a84ff'
    default: return statusColor[node.status]
  }
}
</script>

<template>
  <section v-if="layout.nodes.length" class="dag-graph-section">
    <div class="dag-graph-header">
      <span class="eyebrow">任务流程图</span>
      <span class="dag-stats">
        {{ tasks.length }} 任务 ·
        {{ turns.length }} 对话 ·
        {{ memoryCompactions.length }} 压缩 ·
        {{ layout.edges.length }} 依赖
      </span>
    </div>

    <div class="graph-container">
      <svg
        :viewBox="`0 0 ${layout.width} ${layout.height}`"
        preserveAspectRatio="xMidYMid meet"
        style="width:100%;height:auto;min-height:160px"
      >
        <defs>
          <marker id="dag-arrow" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
            <polygon points="0 0, 7 2.5, 0 5" fill="#636366" />
          </marker>
          <marker id="dag-arrow-conv" markerWidth="5" markerHeight="4" refX="5" refY="2" orient="auto">
            <polygon points="0 0, 5 2, 0 4" fill="#0a84ff" />
          </marker>
        </defs>

        <!-- Edges -->
        <g>
          <path
            v-for="(edge, i) in layout.edges"
            :key="'e' + i"
            :d="getEdgePath(edge)"
            :stroke="edgeStrokeColor(edge)"
            stroke-width="1.2"
            fill="none"
            :marker-end="edgeMarker(edge)"
            :opacity="edgeOpacity(edge)"
            :stroke-dasharray="edgeDashArray(edge)"
          />
        </g>

        <!-- Nodes -->
        <g
          v-for="node in layout.nodes"
          :key="node.id"
          :transform="`translate(${node.x},${node.y})`"
          class="dagn"
          :class="{
            'conv-node': node.type === 'conversation',
            'mem-node': node.type === 'memory',
            'syn-node': node.type === 'synthesis',
          }"
          @click="node.expandable ? toggleNode(node.id) : null"
          :style="{ cursor: node.expandable ? 'pointer' : 'default' }"
        >
          <!-- Conversation nodes: small rounded rect -->
          <template v-if="node.type === 'conversation'">
            <rect
              :width="node.w" :height="node.h" rx="6" ry="6"
              :fill="nodeFillClass(node)"
              :stroke="nodeStrokeColor(node)"
              stroke-width="1"
            />
            <text
              :x="6" y="17"
              font-size="8" font-weight="600" fill="#64d2ff"
            >{{ convIcon(node.turn!) }}</text>
            <text
              :x="18" y="17"
              font-size="8" fill="var(--label)"
              text-anchor="start"
            >{{ node.label }}</text>
          </template>

          <!-- Memory nodes: small diamond -->
          <template v-else-if="node.type === 'memory'">
            <rect
              :width="node.w" :height="node.h" rx="6" ry="6"
              :fill="nodeFillClass(node)"
              :stroke="nodeStrokeColor(node)"
              stroke-width="1"
            />
            <text
              :x="4" y="12"
              font-size="7" fill="#f0a245"
            >🧠</text>
            <text
              :x="18" y="12"
              font-size="7" font-weight="600" fill="var(--label)"
            >{{ node.label }}</text>
            <text
              :x="node.w / 2" y="22"
              font-size="6.5" fill="var(--secondary)"
              text-anchor="middle"
            >{{ node.sub.slice(0, 20) }}</text>
          </template>

          <!-- Start / Synthesis / Task nodes -->
          <template v-else>
            <rect
              :width="node.w" :height="node.h" rx="8" ry="8"
              :fill="nodeFillClass(node)"
              :stroke="nodeStrokeColor(node)"
              stroke-width="1.2"
            />
            <!-- Status dot -->
            <circle
              v-if="node.type === 'task'"
              :cx="10" :cy="14" r="4.5"
              :fill="statusColor[node.status]"
              :class="node.status === 'running' ? 'pulse' : ''"
            />
            <circle
              v-else-if="node.type === 'synthesis'"
              :cx="10" :cy="14" r="4.5"
              :fill="node.status === 'completed' ? '#30d158' : '#636366'"
            />
            <!-- Title -->
            <text
              :x="node.type === 'start' ? 10 : 20" y="18"
              font-size="9" font-weight="600" fill="var(--label)"
              :text-anchor="node.type === 'start' ? 'middle' : 'start'"
            >{{ node.label.length > 14 ? node.label.slice(0, 14) + '…' : node.label }}</text>
            <!-- Sub -->
            <text
              :x="node.type === 'start' ? 10 : 20" y="35"
              font-size="7.5" fill="var(--secondary)"
              :text-anchor="node.type === 'start' ? 'middle' : 'start'"
            >{{ node.sub.slice(0, 20) }}</text>
          </template>

          <!-- Expanded detail -->
          <template v-if="node.expandable && expandedId === node.id">
            <!-- Conversation detail -->
            <rect
              v-if="node.type === 'conversation' && node.turn"
              :x="0" :y="node.h" :width="node.w + 80" height="70" rx="0" ry="0"
              fill="var(--surface)" stroke="var(--separator-soft)" stroke-width="1"
            />
            <template v-if="node.type === 'conversation' && node.turn">
              <text x="8" :y="node.h + 16" font-size="8" fill="var(--secondary)">
                {{ node.turn.brainResponse ? '用户消息' : '对话' }}
              </text>
              <text x="8" :y="node.h + 32" font-size="8" fill="var(--label)">
                {{ node.turn.userMessage.slice(0, 90) }}{{ node.turn.userMessage.length > 90 ? '…' : '' }}
              </text>
              <text v-if="node.turn.brainResponse" x="8" :y="node.h + 50" font-size="8" fill="var(--secondary)">主脑响应</text>
              <text v-if="node.turn.brainResponse" x="8" :y="node.h + 64" font-size="8" fill="var(--label)">
                {{ node.turn.brainResponse.slice(0, 90) }}{{ node.turn.brainResponse.length > 90 ? '…' : '' }}
              </text>
            </template>

            <!-- Task detail with input params -->
            <rect
              v-if="node.type === 'task' && node.task"
              :x="0" :y="node.h" :width="node.w + 70" height="82" rx="0" ry="0"
              fill="var(--surface)" stroke="var(--separator-soft)" stroke-width="1"
            />
            <template v-if="node.type === 'task' && node.task">
              <text x="8" :y="node.h + 16" font-size="8" fill="var(--secondary)">入参 · 目标</text>
              <text x="8" :y="node.h + 32" font-size="8" fill="var(--label)">
                {{ node.task.objective.slice(0, 80) }}{{ node.task.objective.length > 80 ? '…' : '' }}
              </text>
              <text v-if="node.task.write_scope.length" x="8" :y="node.h + 48" font-size="8" fill="var(--secondary)">
                写范围: {{ node.task.write_scope.join(', ').slice(0, 60) }}
              </text>
              <text v-if="node.task.depends_on.length" x="8" :y="node.h + 62" font-size="8" fill="var(--secondary)">
                依赖: {{ node.task.depends_on.join(', ').slice(0, 60) }}
              </text>
              <text x="8" :y="node.h + 78" font-size="8" :fill="statusColor[node.status]">
                {{ taskSummary(node.task.id) || '进行中…' }}
              </text>
            </template>

            <!-- Memory detail -->
            <rect
              v-if="node.type === 'memory' && node.memory"
              :x="0" :y="node.h" :width="node.w + 50" height="45" rx="0" ry="0"
              fill="var(--surface)" stroke="var(--separator-soft)" stroke-width="1"
            />
            <template v-if="node.type === 'memory' && node.memory">
              <text x="8" :y="node.h + 16" font-size="8" fill="var(--secondary)">Agent</text>
              <text x="8" :y="node.h + 32" font-size="8" fill="var(--label)">
                {{ node.memory.agentsCompacted.join(', ').slice(0, 60) }}
              </text>
            </template>

            <!-- Synthesis detail -->
            <rect
              v-if="node.type === 'synthesis'"
              :x="0" :y="node.h" :width="node.w + 70" height="60" rx="0" ry="0"
              fill="var(--surface)" stroke="var(--separator-soft)" stroke-width="1"
            />
            <template v-if="node.type === 'synthesis'">
              <text x="8" :y="node.h + 16" font-size="8" fill="var(--secondary)">最终汇总</text>
              <text x="8" :y="node.h + 34" font-size="8" fill="var(--label)">
                {{ tasks.length }} 个任务已完成，结果已汇流
              </text>
              <text x="8" :y="node.h + 52" font-size="8" :fill="statusColor[node.status]">
                {{ node.status === 'completed' ? '✓ 完成' : node.status === 'running' ? '执行中…' : '等待' }}
              </text>
            </template>
          </template>
        </g>
      </svg>
    </div>

    <div class="graph-legend">
      <span class="legend-item"><span class="legend-dot" style="background:#0a84ff" /> 对话</span>
      <span class="legend-item"><span class="legend-dot" style="background:#0a84ff" /> 主脑</span>
      <span class="legend-item"><span class="legend-dot" style="background:#636366" /> 等待</span>
      <span class="legend-item"><span class="legend-dot" style="background:#0a84ff" /> 执行中</span>
      <span class="legend-item"><span class="legend-dot" style="background:#30d158" /> 完成</span>
      <span class="legend-item"><span class="legend-dot" style="background:#ff453a" /> 失败</span>
      <span class="legend-item"><span class="legend-dot" style="background:#f0a245" /> 记忆压缩</span>
      <span class="legend-item"><span class="legend-dot" style="background:#30d158" /> 汇总</span>
      <span class="legend-hint">点击节点展开详情</span>
    </div>

    <details v-if="contract" class="coordination-contract" style="margin-top:0.5rem">
      <summary>共享接口 / 协议契约</summary>
      <pre>{{ contract }}</pre>
    </details>
  </section>
</template>

<style scoped>
.dag-graph-section { margin-bottom: 0.35rem; }
.dag-graph-header {
  display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.35rem;
}
.dag-stats { font-size: 0.625rem; color: var(--tertiary); }

.graph-container {
  background: var(--surface);
  border: 1px solid var(--separator-soft);
  border-radius: 10px;
  overflow: auto;
  max-height: 300px;
}
.graph-container svg { display: block; }

.dagn rect { transition: stroke-width 0.15s; }
.dagn:hover rect { stroke-width: 1.8; }

.dagn.conv-node:hover rect { stroke-width: 1.5; }

@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.25; } }
.pulse { animation: pulse 1.5s ease-in-out infinite; }

.graph-legend {
  display: flex; flex-wrap: wrap; gap: 0.65rem; align-items: center;
  font-size: 0.625rem; color: var(--tertiary); margin-top: 0.35rem;
}
.legend-item { display: flex; align-items: center; gap: 0.25rem; }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.legend-hint { margin-left: auto; font-style: italic; opacity: 0.7; font-size: 0.55rem; }

.coordination-contract {
  margin-bottom: 10px; padding: 11px 13px;
  border: 1px solid rgba(10,132,255,.22); border-radius: 12px;
  background: rgba(10,132,255,.08);
}
.coordination-contract summary { color: #64d2ff; cursor: pointer; font-size: 0.625rem; font-weight: 600; }
.coordination-contract pre {
  max-height: 200px; overflow: auto; margin: 9px 0 0;
  color: var(--secondary);
  font: 0.5625rem/1.6 ui-monospace,"SFMono-Regular",Menlo,monospace;
  white-space: pre-wrap;
}
</style>
