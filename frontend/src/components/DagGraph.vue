<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PlanTask, RunEvent } from '../types'

const props = defineProps<{
  tasks: PlanTask[]
  events: RunEvent[]
  contract: string
}>()

const expandedId = ref<string | null>(null)

function toggleNode(id: string) {
  expandedId.value = expandedId.value === id ? null : id
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
const statusLabel: Record<string, string> = {
  pending: '等待', running: '执行中', completed: '完成', failed: '失败',
}

interface LayoutNode {
  id: string; label: string; sub: string; depth: number; x: number; y: number
  w: number; h: number; status: string; isStart?: boolean; isEnd?: boolean; task?: PlanTask
}

const nodeW = 146; const nodeH = 48; const hGap = 120; const vGap = 72
const padX = 20; const padY = 32

const layout = computed(() => {
  const tasks = props.tasks
  if (!tasks.length) {
    return { nodes: [] as LayoutNode[], edges: [] as { from: string; to: string }[], width: 400, height: 120 }
  }

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

  const shiftedMaxDepth = maxDepth + 2 // room for start + end
  const maxPerLayer = Math.max(...Array.from(layers.values()).map((l) => l.length), 1)

  const nodes: LayoutNode[] = []
  const edges: { from: string; to: string }[] = []

  // Start node: "主脑规划"
  const startId = '__start__'
  nodes.push({
    id: startId, label: '主脑规划', sub: 'DeepSeek 拆解任务',
    depth: 0, x: padX, y: padY + (maxPerLayer / 2) * vGap - vGap / 2,
    w: nodeW, h: nodeH, status: 'completed', isStart: true,
  })

  // Task nodes at depth + 1
  tasks.forEach((t) => {
    const rawDepth = depths.get(t.id) || 0
    const d = rawDepth + 1 // shift right for start node
    const layerTasks = layers.get(rawDepth) || []
    const idx = layerTasks.indexOf(t)
    const layerCount = layerTasks.length
    const yOff = layerCount === 1 ? 0 : (idx - (layerCount - 1) / 2) * vGap

    nodes.push({
      id: t.id, label: t.title, sub: t.agent,
      depth: d,
      x: padX + d * (nodeW + hGap),
      y: padY + (maxPerLayer / 2) * vGap + yOff - vGap / 2,
      w: nodeW, h: nodeH, status: taskStatus(t.id), task: t,
    })

    // Edge from dependencies (or start node if no deps)
    if (t.depends_on.length) {
      t.depends_on.forEach((depId) => edges.push({ from: depId, to: t.id }))
    } else {
      edges.push({ from: startId, to: t.id })
    }
  })

  // End node: "结果汇总"
  const endId = '__end__'
  const endDepth = shiftedMaxDepth
  const lastLayerTasks = layers.get(maxDepth) || []
  nodes.push({
    id: endId, label: '结果汇总', sub: 'DeepSeek 验收',
    depth: endDepth, x: padX + endDepth * (nodeW + hGap),
    y: padY + (maxPerLayer / 2) * vGap - vGap / 2,
    w: nodeW, h: nodeH, status: 'pending', isEnd: true,
  })
  // Connect all leaf tasks to end
  tasks.forEach((t) => {
    const isLeaf = !tasks.some((other) => other.depends_on.includes(t.id))
    if (isLeaf) edges.push({ from: t.id, to: endId })
  })

  const width = padX * 2 + (shiftedMaxDepth + 1) * (nodeW + hGap)
  const height = padY * 2 + maxPerLayer * vGap

  return { nodes, edges, width, height }
})
</script>

<template>
  <section v-if="tasks.length" class="dag-graph-section">
    <div class="dag-graph-header">
      <span class="eyebrow">任务流程图</span>
      <span class="dag-stats">{{ tasks.length }} 个任务节点 · {{ layout.edges.length }} 条依赖</span>
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
        </defs>

        <!-- Edges -->
        <g>
          <path
            v-for="(edge, i) in layout.edges"
            :key="'e' + i"
            :d="(() => {
              const fromNd = layout.nodes.find(n => n.id === edge.from)
              const toNd = layout.nodes.find(n => n.id === edge.to)
              if (!fromNd || !toNd) return ''
              const x1 = fromNd.x + fromNd.w
              const y1 = fromNd.y + fromNd.h / 2
              const x2 = toNd.x
              const y2 = toNd.y + toNd.h / 2
              const mx = (x1 + x2) / 2
              return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`
            })()"
            stroke="#636366" stroke-width="1.2" fill="none"
            marker-end="url(#dag-arrow)" opacity="0.6"
          />
        </g>

        <!-- Nodes -->
        <g
          v-for="node in layout.nodes"
          :key="node.id"
          :transform="`translate(${node.x},${node.y})`"
          class="dagn"
          @click="node.task ? toggleNode(node.id) : null"
          :style="{ cursor: node.task ? 'pointer' : 'default' }"
        >
          <rect
            :width="node.w" :height="node.h" rx="8" ry="8"
            :fill="node.isStart ? 'rgba(10,132,255,0.1)' : node.isEnd ? 'rgba(48,209,88,0.08)' : statusColor[node.status] + '12'"
            :stroke="node.isStart ? '#0a84ff' : node.isEnd ? '#30d158' : statusColor[node.status]"
            stroke-width="1.2"
          />
          <!-- Status dot (only for task nodes) -->
          <circle
            v-if="node.task"
            :cx="10" :cy="14" r="4.5"
            :fill="statusColor[node.status]"
            :class="node.status === 'running' ? 'pulse' : ''"
          />
          <!-- Title -->
          <text
            :x="node.task ? 20 : 10" y="18"
            font-size="10.5" font-weight="600" fill="var(--label)"
            :text-anchor="node.task ? 'start' : 'middle'"
          >
            {{ node.label.length > 16 ? node.label.slice(0, 16) + '…' : node.label }}
          </text>
          <!-- Sub label -->
          <text
            :x="node.task ? 20 : 10" y="35"
            font-size="9" fill="var(--secondary)"
            :text-anchor="node.task ? 'start' : 'middle'"
          >
            {{ node.task ? node.sub : node.sub }}
          </text>

          <!-- Expanded detail for task nodes -->
          <template v-if="node.task && expandedId === node.id">
            <rect
              :x="0" :y="node.h" :width="node.w + 60" height="70" rx="0" ry="0"
              fill="var(--surface)" stroke="var(--separator-soft)" stroke-width="1"
            />
            <text x="8" :y="node.h + 18" font-size="9" fill="var(--secondary)">目标</text>
            <text x="8" :y="node.h + 34" font-size="9" fill="var(--label)">
              {{ node.task.objective.slice(0, 70) }}{{ node.task.objective.length > 70 ? '…' : '' }}
            </text>
            <text v-if="taskSummary(node.task.id)" x="8" :y="node.h + 52" font-size="9" fill="var(--secondary)">结果</text>
            <text x="8" :y="node.h + 66" font-size="9" fill="var(--green)">
              {{ taskSummary(node.task.id) || '进行中…' }}
            </text>
          </template>
        </g>
      </svg>
    </div>

    <div class="graph-legend">
      <span class="legend-item"><span class="legend-dot" style="background:#0a84ff" /> 主脑</span>
      <span class="legend-item"><span class="legend-dot" style="background:#636366" /> 等待</span>
      <span class="legend-item"><span class="legend-dot" style="background:#0a84ff" /> 执行中</span>
      <span class="legend-item"><span class="legend-dot" style="background:#30d158" /> 完成</span>
      <span class="legend-item"><span class="legend-dot" style="background:#ff453a" /> 失败</span>
      <span class="legend-item"><span class="legend-dot" style="background:#30d158" /> 结果</span>
      <span class="legend-hint">点击任务节点展开详情</span>
    </div>

    <details v-if="contract" class="coordination-contract" style="margin-top:0.5rem">
      <summary>DeepSeek 共享接口 / 协议契约</summary>
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
  max-height: 380px;
}
.graph-container svg { display: block; }

.dagn rect { transition: stroke-width 0.15s; }
.dagn:hover rect { stroke-width: 2; }

@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.25; } }
.pulse { animation: pulse 1.5s ease-in-out infinite; }

.graph-legend {
  display: flex; gap: 0.85rem; align-items: center;
  font-size: 0.625rem; color: var(--tertiary); margin-top: 0.35rem;
}
.legend-item { display: flex; align-items: center; gap: 0.25rem; }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.legend-hint { margin-left: auto; font-style: italic; opacity: 0.7; }
</style>
