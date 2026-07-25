<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import NodeErrorOverlay from './NodeErrorOverlay.vue'
import type { ExecutionNode, NodeEdge, NodeStatus } from '../types'

const props = defineProps<{
  nodes: ExecutionNode[]
  edges: NodeEdge[]
  selectedNodeId: string | null
  filterStatus: NodeStatus | 'all'
}>()

const emit = defineEmits<{
  selectNode: [nodeId: string]
  interruptNode: [nodeId: string]
}>()

// ==================== 布局常量 ====================
const NODE_W = 220
const NODE_H = 72
const NODE_GAP_Y = 60
const CANVAS_PADDING = 60
const DEPTH_OFFSET_X = 280

const svgRef = ref<SVGSVGElement | null>(null)
const viewBox = ref({ x: 0, y: 0, w: 800, h: 600 })
const isDragging = ref(false)
const dragStart = ref({ x: 0, y: 0 })
const vbStart = ref({ x: 0, y: 0 })

// ==================== 节点拖动 ====================
const dragNode = ref<string | null>(null)
const dragOffset = ref({ x: 0, y: 0 })
const customPositions = ref<Record<string, { x: number; y: number }>>({})

const POS_KEY = 'dag-node-positions'

function loadPositions() {
  try {
    const raw = localStorage.getItem(POS_KEY)
    if (raw) customPositions.value = JSON.parse(raw)
  } catch { /* */ }
}
function savePositions() {
  try { localStorage.setItem(POS_KEY, JSON.stringify(customPositions.value)) } catch { /* */ }
}
onMounted(loadPositions)

// ==================== 布局计算 ====================
interface NodePosition { x: number; y: number; w: number; h: number }

const nodePositions = computed<Map<string, NodePosition>>(() => {
  const map = new Map<string, NodePosition>()
  if (!props.nodes.length) return map

  const byDepth = new Map<number, ExecutionNode[]>()
  for (const n of props.nodes) {
    const d = n.depth ?? 0
    const list = byDepth.get(d) || []
    list.push(n); byDepth.set(d, list)
  }

  for (const [depth, nodesAtDepth] of byDepth) {
    nodesAtDepth.forEach((node, idx) => {
      const totalAtDepth = nodesAtDepth.length
      // Check for saved position first
      const saved = customPositions.value[node.id]
      const x = saved ? saved.x : CANVAS_PADDING + depth * DEPTH_OFFSET_X
      const y = saved ? saved.y : CANVAS_PADDING + idx * (NODE_H + NODE_GAP_Y)
        - (totalAtDepth - 1) * (NODE_H + NODE_GAP_Y) / 2 + 300
      map.set(node.id, { x, y, w: NODE_W, h: NODE_H })
    })
  }
  return map
})

const svgSize = computed(() => {
  let maxX = 800, maxY = 600
  for (const pos of nodePositions.value.values()) {
    maxX = Math.max(maxX, pos.x + pos.w + CANVAS_PADDING)
    maxY = Math.max(maxY, pos.y + pos.h + CANVAS_PADDING)
  }
  return { w: maxX, h: maxY }
})

// ==================== 边 ====================
function edgePath(from: NodePosition, to: NodePosition): string {
  const startX = from.x + from.w
  const startY = from.y + from.h / 2
  const endX = to.x
  const endY = to.y + to.h / 2
  const midX = (startX + endX) / 2
  return `M ${startX},${startY} C ${midX},${startY} ${midX},${endY} ${endX},${endY}`
}

// ==================== 颜色 ====================
function colorFor(node: ExecutionNode) {
  switch (node.status) {
    case 'running': return { fill: 'rgba(91,160,245,.12)', stroke: '#5ba0f5' }
    case 'completed': return { fill: 'rgba(77,184,107,.12)', stroke: '#4db86b' }
    case 'failed': return { fill: 'rgba(255,87,87,.12)', stroke: '#ff5757' }
    default: return { fill: 'var(--el-fill-color-light)', stroke: 'var(--el-border-color)' }
  }
}

// ==================== 事件处理 ====================
function onNodeClick(nodeId: string) {
  emit('selectNode', nodeId)
}

// Node drag
function onNodeMouseDown(e: MouseEvent, nodeId: string) {
  if (e.button !== 0) return
  e.stopPropagation()
  const pos = nodePositions.value.get(nodeId)
  if (!pos) return
  dragNode.value = nodeId
  dragOffset.value = { x: e.clientX - pos.x, y: e.clientY - pos.y }
}
function onNodeMouseMove(e: MouseEvent) {
  if (!dragNode.value) return
  const svg = svgRef.value
  if (!svg) return
  const pt = svg.createSVGPoint()
  pt.x = e.clientX; pt.y = e.clientY
  const ctm = svg.getScreenCTM()
  if (!ctm) return
  const svgPt = pt.matrixTransform(ctm.inverse())
  customPositions.value[dragNode.value] = {
    x: Math.round(svgPt.x - dragOffset.value.x),
    y: Math.round(svgPt.y - dragOffset.value.y),
  }
}
function onNodeMouseUp() {
  if (dragNode.value) { savePositions(); dragNode.value = null }
}

// Canvas pan
function onSvgMouseDown(e: MouseEvent) {
  if (e.target !== svgRef.value && !(e.target as Element)?.classList?.contains('svg-bg')) return
  isDragging.value = true
  dragStart.value = { x: e.clientX, y: e.clientY }
  vbStart.value = { x: viewBox.value.x, y: viewBox.value.y }
}
function onSvgMouseMove(e: MouseEvent) {
  if (dragNode.value) { onNodeMouseMove(e); return }
  if (!isDragging.value) return
  viewBox.value.x = vbStart.value.x - (e.clientX - dragStart.value.x)
  viewBox.value.y = vbStart.value.y - (e.clientY - dragStart.value.y)
}
function onSvgMouseUp() {
  isDragging.value = false
  onNodeMouseUp()
}

// ==================== 缩放 ====================
const MIN_ZOOM = 0.6
const MAX_ZOOM = 2.5
function onWheel(e: WheelEvent) {
  e.preventDefault()
  const baseW = svgSize.value.w + 40
  const factor = e.deltaY > 0 ? 1.15 : 0.87
  const newW = viewBox.value.w * factor
  const zoomRatio = newW / baseW
  if (zoomRatio < MIN_ZOOM || zoomRatio > MAX_ZOOM) return
  viewBox.value.w = newW
  viewBox.value.h *= factor
}
function fitView() {
  const w = Math.max(900, svgSize.value.w + 40)
  const h = Math.max(600, svgSize.value.h + 40)
  viewBox.value = { x: -20, y: -20, w, h }
}
watch(() => props.nodes.length, () => fitView())

function handleKey(e: KeyboardEvent) {
  if (e.key === 'f' || e.key === 'F') { fitView(); e.preventDefault() }
}
function selectNodeFromEvent(e: CustomEvent) { emit('selectNode', e.detail.nodeId) }

onMounted(() => {
  document.addEventListener('keydown', handleKey)
  window.addEventListener('resize', fitView)
  window.addEventListener('mouseup', onSvgMouseUp)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKey)
  window.removeEventListener('resize', fitView)
  window.removeEventListener('mouseup', onSvgMouseUp)
})
defineExpose({ fitView })
</script>

<template>
  <div class="graph-container" @mouseup="onSvgMouseUp">
    <svg
      ref="svgRef"
      :viewBox="`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`"
      class="graph-svg"
      @mousedown="onSvgMouseDown"
      @mousemove="onSvgMouseMove"
      @wheel="onWheel"
      @selectNode="selectNodeFromEvent"
    >
      <defs>
        <marker id="arrowHead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--el-border-color)" />
        </marker>
      </defs>

      <rect class="svg-bg" :x="viewBox.x" :y="viewBox.y" :width="viewBox.w" :height="viewBox.h" fill="transparent" />

      <!-- 边 -->
      <g class="edges-layer">
        <path
          v-for="edge in edges"
          :key="`${edge.from}-${edge.to}`"
          v-show="nodePositions.has(edge.from) && nodePositions.has(edge.to)"
          :d="edgePath(nodePositions.get(edge.from)!, nodePositions.get(edge.to)!)"
          fill="none"
          stroke="var(--el-border-color)"
          stroke-width="2"
          marker-end="url(#arrowHead)"
        />
      </g>

      <!-- 节点 -->
      <g class="nodes-layer">
        <g
          v-for="node in nodes"
          :key="node.id"
          v-show="nodePositions.has(node.id)"
          :transform="`translate(${nodePositions.get(node.id)!.x}, ${nodePositions.get(node.id)!.y})`"
          class="graph-node"
          :class="[`node-${node.status}`, { 'node-selected': selectedNodeId === node.id }]"
          :style="{ cursor: dragNode === node.id ? 'grabbing' : 'grab' }"
          @mousedown="onNodeMouseDown($event, node.id)"
          @click.stop="onNodeClick(node.id)"
        >
          <rect :x="0" :y="0" :width="NODE_W" :height="NODE_H" :rx="10"
            :fill="colorFor(node).fill" :stroke="colorFor(node).stroke"
            :stroke-width="selectedNodeId === node.id ? 2 : (node.status === 'failed' ? 2 : 1)"
            class="node-rect" />
          <rect v-if="node.status === 'running'" :x="-2" :y="-2" :width="NODE_W+4" :height="NODE_H+4"
            :rx="12" fill="none" :stroke="colorFor(node).stroke" stroke-width="1.5" stroke-dasharray="4 2" class="node-pulse" />
          <NodeErrorOverlay v-if="node.hasError" :error="node.error!" :x="NODE_W-20" :y="4" />

          <text :x="12" :y="22" font-size="12" font-weight="600" fill="var(--el-text-color-primary)">{{ node.name }}</text>
          <text :x="12" :y="40" font-size="11" fill="var(--el-text-color-secondary)">{{ node.sub?.slice(0, 35) || '' }}</text>
          <text v-if="node.durationMs" :x="NODE_W-10" :y="20" text-anchor="end" font-size="10" fill="var(--el-text-color-secondary)">
            {{ (node.durationMs / 1000).toFixed(1) }}s
          </text>
        </g>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.graph-container { width: 100%; height: 100%; overflow: hidden; }
.graph-svg { width: 100%; height: 100%; display: block; }
.graph-node { transition: transform 0.08s ease; }
.node-pulse { animation: pulse-ring 2s ease-in-out infinite; }
@keyframes pulse-ring { 0%,100% { opacity:1 } 50% { opacity:.3 } }
</style>
