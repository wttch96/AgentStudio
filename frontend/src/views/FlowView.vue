<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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
const viewBox = ref({ x: 0, y: 0, w: 800, h: 500 })
const isDragging = ref(false)
const dragStart = ref({ x: 0, y: 0 })
const vbStart = ref({ x: 0, y: 0 })

// ----------------------------------------------------------------- layout
const NODE_W = 200
const NODE_H = 56
const DEPTH_X = 280
const PAD = 60

interface FlowNode { id: string; agent: string; title: string; depends_on: string[]; objective?: string }
const flow = computed<FlowDefinition | null>(() => flows.value.find(f => f.name === selectedName.value) || null)
const nodes = computed<FlowNode[]>(() => flow.value?.nodes || [])

// load full flow detail when selected
const flowDetail = ref<FlowDefinition | null>(null)
watch(selectedName, async (name) => {
  if (!name) { flowDetail.value = null; return }
  try { flowDetail.value = await api.flow(name) } catch { flowDetail.value = null }
})
const detailNodes = computed<FlowNode[]>(() => flowDetail.value?.nodes || [])
const allNodes = computed<FlowNode[]>(() => detailNodes.value.length ? detailNodes.value : nodes.value)

interface NodePos { x: number; y: number }
const positions = computed<Map<string, NodePos>>(() => {
  const map = new Map<string, NodePos>()
  const ns = allNodes.value
  if (!ns.length) return map
  const depthMap = new Map<string, number>()
  function getDepth(id: string, visited = new Set<string>()): number {
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

const edges = computed<Array<{from:string;to:string}>>(() => {
  const result: Array<{from:string;to:string}> = []
  for (const n of allNodes.value) {
    for (const d of n.depends_on) result.push({ from: d, to: n.id })
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
function onWheel(e: WheelEvent) {
  e.preventDefault()
  const factor = e.deltaY > 0 ? 1.12 : 0.89
  const baseW = svgSize.value.w
  const newW = viewBox.value.w * factor
  if (newW / baseW < 0.5 || newW / baseW > 3) return
  viewBox.value.w = newW
  viewBox.value.h *= factor
}
function onMouseDown(e: MouseEvent) {
  isDragging.value = true
  dragStart.value = { x: e.clientX, y: e.clientY }
  vbStart.value = { x: viewBox.value.x, y: viewBox.value.y }
}
function onMouseMove(e: MouseEvent) {
  if (!isDragging.value) return
  viewBox.value.x = vbStart.value.x - (e.clientX - dragStart.value.x)
  viewBox.value.y = vbStart.value.y - (e.clientY - dragStart.value.y)
}
function onMouseUp() { isDragging.value = false }
function fitView() {
  viewBox.value = { x: -20, y: -20, w: Math.max(800, svgSize.value.w), h: Math.max(500, svgSize.value.h) }
}
watch(() => allNodes.value.length, () => fitView())

// ----------------------------------------------------------------- execute flow
async function executeFlow() {
  if (!selectedName.value) return
  running.value = true; runStatus.value = 'queued'
  try {
    const run = await api.createRun('/+' + selectedName.value)
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
      <div v-if="loading" class="d-flex align-items-center justify-content-center h-100">
        <ElIcon class="is-loading"><Loading /></ElIcon>
      </div>
      <svg
        v-else-if="allNodes.length"
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
          <line
            v-if="positions.get(e.from) && positions.get(e.to)"
            :x1="positions.get(e.from)!.x + NODE_W"
            :y1="positions.get(e.from)!.y + NODE_H/2"
            :x2="positions.get(e.to)!.x"
            :y2="positions.get(e.to)!.y + NODE_H/2"
            stroke="var(--el-border-color)"
            stroke-width="1.5"
            marker-end="url(#arrow)"
          />
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
              :width="NODE_W" :height="NODE_H" rx="8"
              :fill="runId ? (nodeStatuses[n.id] === 'completed' ? 'rgba(77,184,107,.12)' : nodeStatuses[n.id] === 'failed' ? 'rgba(255,87,87,.12)' : nodeStatuses[n.id] === 'running' ? 'rgba(91,160,245,.12)' : 'var(--el-fill-color-light)') : 'var(--el-fill-color-light)'"
              :stroke="runId ? statusColor(nodeStatuses[n.id] || 'pending') : 'var(--el-border-color)'"
              stroke-width="1.5"
            />
            <text :x="10" :y="20" font-size="12" fill="var(--el-text-color-primary)" font-weight="600">{{ n.title }}</text>
            <text :x="10" :y="38" font-size="11" fill="var(--el-text-color-secondary)">{{ n.agent }}</text>
            <text v-if="runId && nodeStatuses[n.id]" :x="NODE_W-10" :y="20" text-anchor="end" font-size="10" :fill="statusColor(nodeStatuses[n.id])">
              {{ nodeStatuses[n.id] === 'completed' ? '✓' : nodeStatuses[n.id] === 'failed' ? '✗' : '●' }}
            </text>
          </g>
        </g>
      </svg>
      <div v-else class="d-flex align-items-center justify-content-center h-100 text-secondary">
        暂无流程定义。在 templates/flows/ 中创建 YAML 流程文件。
      </div>
    </div>
  </div>
</template>
