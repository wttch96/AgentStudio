<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { FlowDefinition } from '../types'

// ----------------------------------------------------------------- state
const flows = ref<FlowDefinition[]>([])
const selectedName = ref('')
const loading = ref(true)
const running = ref(false)
const runId = ref<string | null>(null)
const runStatus = ref('')
const nodeStatuses = ref<Record<string, string>>({})

// DAG view
const svgRef = ref<SVGSVGElement | null>(null)
const viewBox = ref({ x: 0, y: 0, w: 800, h: 500 })
const fittedViewBox = ref({ x: 0, y: 0, w: 800, h: 500 })
const zoomLevel = ref(1)
const isDragging = ref(false)
const dragStart = ref({ x: 0, y: 0 })
const vbStart = ref({ x: 0, y: 0 })

// ----------------------------------------------------------------- layout
const NODE_W = 200
const NODE_H = 56
const DEPTH_X = 280
const PAD = 60

interface FlowNode { id: string; agent: string; title: string; depends_on: string[]; objective?: string; kind?: 'agent' | 'condition' | 'parallel' | 'loop' }
const flow = computed<FlowDefinition | null>(() => flows.value.find(f => f.name === selectedName.value) || null)
const nodes = computed<FlowNode[]>(() => flow.value?.nodes || [])

// load full flow detail when selected
const flowDetail = ref<FlowDefinition | null>(null)
watch(selectedName, async (name) => {
  if (!name) { flowDetail.value = null; return }
  try { flowDetail.value = await api.flow(name) } catch { flowDetail.value = null }
})
const detailNodes = computed<FlowNode[]>(() => {
  const detail = flowDetail.value
  if (!detail) return []
  return [
    ...detail.nodes.map(node => ({ ...node, kind: 'agent' as const })),
    ...(detail.conditions || []).map(block => ({
      id: block.id, agent: '条件分支', title: block.condition,
      objective: block.condition, depends_on: [], kind: 'condition' as const,
    })),
    ...(detail.parallels || []).map(block => ({
      id: block.id, agent: `并行 × ${block.items.length}`, title: '并行分流/汇流',
      objective: block.items.join(', '), depends_on: [], kind: 'parallel' as const,
    })),
    ...(detail.loops || []).map(block => ({
      id: block.id, agent: `循环 ≤ ${block.max_iterations}`, title: block.condition,
      objective: block.condition, depends_on: [], kind: 'loop' as const,
    })),
  ]
})
const allNodes = computed<FlowNode[]>(() => detailNodes.value.length ? detailNodes.value : nodes.value)

interface NodePos { x: number; y: number }
const positions = computed<Map<string, NodePos>>(() => {
  const map = new Map<string, NodePos>()
  const ns = allNodes.value
  if (!ns.length) return map
  const depthMap = new Map<string, number>()
  const orderedSteps = flowDetail.value?.steps || []
  orderedSteps.forEach((id, index) => depthMap.set(id, index))
  function getDepth(id: string, visited = new Set<string>()): number {
    if (depthMap.has(id)) return depthMap.get(id)!
    if (visited.has(id)) return depthMap.get(id) || 0
    visited.add(id)
    const node = ns.find(n => n.id === id)
    if (!node || !node.depends_on.length) { depthMap.set(id, 0); return 0 }
    let maxD = 0
    for (const d of node.depends_on) maxD = Math.max(maxD, getDepth(d, visited) + 1)
    depthMap.set(id, maxD)
    return maxD
  }
  for (const n of ns) getDepth(n.id)

  const byDepth = new Map<number, FlowNode[]>()
  for (const n of ns) {
    const d = depthMap.get(n.id) || 0
    const list = byDepth.get(d) || []
    list.push(n); byDepth.set(d, list)
  }
  for (const [depth, ns] of byDepth) {
    ns.forEach((n, i) => {
      const y = PAD + i * (NODE_H + 40) - (ns.length - 1) * (NODE_H + 40) / 2 + 250
      map.set(n.id, { x: PAD + depth * DEPTH_X, y })
    })
  }
  return map
})

const edges = computed<Array<{from:string;to:string;label?:string;loop?:boolean}>>(() => {
  const result: Array<{from:string;to:string;label?:string;loop?:boolean}> = []
  for (const n of allNodes.value) {
    for (const d of n.depends_on) result.push({ from: d, to: n.id })
  }
  const detail = flowDetail.value
  for (const block of detail?.conditions || []) {
    result.push({ from: block.id, to: block.then_branch, label: 'true' })
    if (block.else_branch) result.push({ from: block.id, to: block.else_branch, label: 'false' })
  }
  for (const block of detail?.parallels || []) {
    for (const item of block.items) result.push({ from: block.id, to: item, label: 'parallel' })
  }
  for (const block of detail?.loops || []) {
    result.push({ from: block.id, to: block.body, label: 'body' })
    result.push({ from: block.body, to: block.id, label: 'repeat', loop: true })
  }
  const steps = detail?.steps || []
  for (let index = 1; index < steps.length; index++) {
    if (!result.some(edge => edge.from === steps[index - 1] && edge.to === steps[index])) {
      result.push({ from: steps[index - 1], to: steps[index] })
    }
  }
  return result
})

const svgSize = computed(() => {
  let maxX = 800, maxY = 500
  for (const p of positions.value.values()) {
    maxX = Math.max(maxX, p.x + NODE_W + PAD)
    maxY = Math.max(maxY, p.y + NODE_H + PAD)
  }
  return { w: maxX, h: maxY }
})

// ----------------------------------------------------------------- zoom / pan
const MIN_ZOOM = 0.2
const MAX_ZOOM = 1.5
function setZoom(nextZoom: number) {
  const clampedZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom))
  if (Math.abs(clampedZoom - zoomLevel.value) < 0.0001) return
  const centerX = viewBox.value.x + viewBox.value.w / 2
  const centerY = viewBox.value.y + viewBox.value.h / 2
  const nextW = fittedViewBox.value.w / clampedZoom
  const nextH = fittedViewBox.value.h / clampedZoom
  viewBox.value = {
    x: centerX - nextW / 2,
    y: centerY - nextH / 2,
    w: nextW,
    h: nextH,
  }
  zoomLevel.value = clampedZoom
}
function onWheel(e: WheelEvent) {
  e.preventDefault()
  setZoom(zoomLevel.value * (e.deltaY > 0 ? 1 / 1.15 : 1.15))
}
function onMouseDown(e: MouseEvent) {
  isDragging.value = true
  dragStart.value = { x: e.clientX, y: e.clientY }
  vbStart.value = { x: viewBox.value.x, y: viewBox.value.y }
}
function onMouseMove(e: MouseEvent) {
  if (!isDragging.value) return
  const svg = svgRef.value
  const scaleX = viewBox.value.w / (svg?.clientWidth || 1)
  const scaleY = viewBox.value.h / (svg?.clientHeight || 1)
  viewBox.value.x = vbStart.value.x - (e.clientX - dragStart.value.x) * scaleX
  viewBox.value.y = vbStart.value.y - (e.clientY - dragStart.value.y) * scaleY
}
function onMouseUp() { isDragging.value = false }
function fitView() {
  const contentW = Math.max(1, svgSize.value.w)
  const contentH = Math.max(1, svgSize.value.h)
  const svg = svgRef.value
  const viewportAspect = (svg?.clientWidth || 800) / (svg?.clientHeight || 500)
  const contentAspect = contentW / contentH
  const fittedW = contentAspect > viewportAspect ? contentW : contentH * viewportAspect
  const fittedH = contentAspect > viewportAspect ? contentW / viewportAspect : contentH
  const next = {
    x: (contentW - fittedW) / 2,
    y: (contentH - fittedH) / 2,
    w: fittedW,
    h: fittedH,
  }
  fittedViewBox.value = next
  viewBox.value = { ...next }
  zoomLevel.value = 1
}
watch(
  () => `${selectedName.value}:${allNodes.value.map(node => node.id).join('|')}`,
  async () => {
    await nextTick()
    fitView()
  },
)

// ----------------------------------------------------------------- execute flow
async function executeFlow() {
  if (!selectedName.value) return
  running.value = true; runStatus.value = 'queued'
  try {
    const run = await api.executeFlow(selectedName.value, {
      objective: flow.value?.description || selectedName.value,
      inputs: { prompt: flow.value?.description || '' },
    })
    runId.value = run.id; runStatus.value = run.status
    pollStatus()
  } catch (e) { runStatus.value = 'failed'; running.value = false }
}
function pollStatus() {
  const interval = setInterval(async () => {
    if (!runId.value) { clearInterval(interval); return }
    try {
      const flowRun = await api.run(runId.value) as any
      runStatus.value = flowRun.status || 'running'
      if (flowRun.events) {
        for (const ev of flowRun.events) {
          if (ev.type === 'node.completed' || ev.type === 'node.failed') {
            const nid = ev.payload?.node_id || ev.task_id
            if (nid) nodeStatuses.value[nid] = ev.type === 'node.completed' ? 'completed' : 'failed'
          }
        }
      }
      if (flowRun.status !== 'queued' && flowRun.status !== 'running') {
        clearInterval(interval); running.value = false
      }
    } catch { clearInterval(interval); running.value = false }
  }, 600)
}

function statusColor(s: string) {
  return s === 'completed' ? '#4db86b' : s === 'failed' ? '#ff5757' : s === 'running' ? '#5ba0f5' : '#636366'
}

// ----------------------------------------------------------------- init
onMounted(async () => {
  try { flows.value = (await api.flows()).items } catch { /* */ }
  if (flows.value.length) selectedName.value = flows.value[0].name
  loading.value = false
})
</script>

<template>
  <div class="d-flex flex-column h-100">
    <!-- Header -->
    <div class="d-flex align-items-center gap-2 p-2 border-bottom">
      <h6 class="mb-0 me-2">流程控制</h6>
      <ElSelect v-model="selectedName" size="small" style="width:200px" :loading="loading">
        <ElOption v-for="f in flows" :key="f.name" :value="f.name" :label="`${f.name} (v${f.version})`" />
      </ElSelect>
      <ElButton type="primary" size="small" :disabled="!selectedName || running" @click="executeFlow">
        {{ running ? '执行中…' : '执行流程' }}
      </ElButton>
      <ElTag v-if="runStatus" size="small" :type="runStatus === 'completed' ? 'success' : runStatus === 'failed' ? 'danger' : runStatus === 'running' ? 'primary' : 'info'">
        {{ runStatus }}
      </ElTag>
      <span class="ms-auto text-secondary small">
        {{ flow ? `${flow.description} (v${flow.version})` : '选择一个流程' }}
      </span>
    </div>

    <!-- DAG Canvas -->
    <div class="flex-grow-1 position-relative" style="background:var(--el-bg-color-page)">
      <div
        v-if="!loading && allNodes.length"
        class="position-absolute top-0 end-0 m-2 px-2 py-1 rounded border text-secondary small"
        style="z-index:2;background:color-mix(in srgb, var(--el-bg-color) 88%, transparent);pointer-events:none"
      >
        {{ zoomLevel.toFixed(2) }}×
      </div>
      <div v-if="loading" class="d-flex align-items-center justify-content-center h-100">
        <ElIcon class="is-loading"><Loading /></ElIcon>
      </div>
      <svg
        v-if="!loading && allNodes.length"
        ref="svgRef"
        :viewBox="`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`"
        class="w-100 h-100"
        style="cursor:grab"
        @wheel="onWheel"
        @mousedown="onMouseDown"
        @mousemove="onMouseMove"
        @mouseup="onMouseUp"
        @mouseleave="onMouseUp"
      >
        <!-- Edges -->
        <g v-for="e in edges" :key="`${e.from}-${e.to}`">
          <path
            v-if="positions.get(e.from) && positions.get(e.to)"
            :d="e.loop
              ? `M ${positions.get(e.from)!.x + NODE_W/2} ${positions.get(e.from)!.y + NODE_H} C ${positions.get(e.from)!.x + NODE_W/2} ${positions.get(e.from)!.y + 120}, ${positions.get(e.to)!.x + NODE_W/2} ${positions.get(e.to)!.y + 120}, ${positions.get(e.to)!.x + NODE_W/2} ${positions.get(e.to)!.y + NODE_H}`
              : `M ${positions.get(e.from)!.x + NODE_W} ${positions.get(e.from)!.y + NODE_H/2} C ${(positions.get(e.from)!.x + NODE_W + positions.get(e.to)!.x)/2} ${positions.get(e.from)!.y + NODE_H/2}, ${(positions.get(e.from)!.x + NODE_W + positions.get(e.to)!.x)/2} ${positions.get(e.to)!.y + NODE_H/2}, ${positions.get(e.to)!.x} ${positions.get(e.to)!.y + NODE_H/2}`"
            fill="none"
            stroke="var(--el-border-color)"
            stroke-width="1.5"
            marker-end="url(#arrow)"
          />
          <text v-if="e.label && positions.get(e.from) && positions.get(e.to)"
            :x="(positions.get(e.from)!.x + NODE_W + positions.get(e.to)!.x)/2"
            :y="(positions.get(e.from)!.y + positions.get(e.to)!.y)/2 + NODE_H/2 - 5"
            text-anchor="middle" font-size="9" fill="var(--el-text-color-secondary)">{{ e.label }}</text>
        </g>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--el-border-color)" />
          </marker>
        </defs>
        <!-- Nodes -->
        <g v-for="n in allNodes" :key="n.id">
          <g v-if="positions.get(n.id)" :transform="`translate(${positions.get(n.id)!.x}, ${positions.get(n.id)!.y})`">
            <rect
              v-if="n.kind !== 'condition'"
              :width="NODE_W" :height="NODE_H" rx="8"
              :fill="runId ? (nodeStatuses[n.id] === 'completed' ? 'rgba(77,184,107,.12)' : nodeStatuses[n.id] === 'failed' ? 'rgba(255,87,87,.12)' : nodeStatuses[n.id] === 'running' ? 'rgba(91,160,245,.12)' : 'var(--el-fill-color-light)') : 'var(--el-fill-color-light)'"
              :stroke="runId ? statusColor(nodeStatuses[n.id] || 'pending') : 'var(--el-border-color)'"
              stroke-width="1.5"
            />
            <polygon
              v-else
              :points="`${NODE_W/2},0 ${NODE_W},${NODE_H/2} ${NODE_W/2},${NODE_H} 0,${NODE_H/2}`"
              fill="var(--el-fill-color-light)" stroke="var(--el-color-warning)" stroke-width="1.5"
            />
            <text :x="10" :y="20" font-size="12" fill="var(--el-text-color-primary)" font-weight="600">{{ n.title }}</text>
            <text :x="10" :y="38" font-size="11" fill="var(--el-text-color-secondary)">{{ n.agent }}</text>
            <text v-if="runId && nodeStatuses[n.id]" :x="NODE_W-10" :y="20" text-anchor="end" font-size="10" :fill="statusColor(nodeStatuses[n.id])">
              {{ nodeStatuses[n.id] === 'completed' ? '✓' : nodeStatuses[n.id] === 'failed' ? '✗' : '●' }}
            </text>
          </g>
        </g>
      </svg>
      <div v-else-if="!loading" class="d-flex align-items-center justify-content-center h-100 text-secondary">
        暂无流程定义。在 .workspace/&lt;project&gt;/flows/ 中创建 YAML 流程文件。
      </div>
    </div>
  </div>
</template>
