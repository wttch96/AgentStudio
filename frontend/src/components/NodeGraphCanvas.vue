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
const NODE_W = 180
const NODE_H = 64
const NODE_GAP_X = 60
const NODE_GAP_Y = 90
const CANVAS_PADDING = 40
const DEPTH_OFFSET_X = 240

// SVG viewport ref
const svgRef = ref<SVGSVGElement | null>(null)
const viewBox = ref({ x: 0, y: 0, w: 800, h: 600 })
const isDragging = ref(false)
const dragStart = ref({ x: 0, y: 0 })
const vbStart = ref({ x: 0, y: 0 })

// ==================== 布局计算 ====================
interface NodePosition {
  x: number; y: number; w: number; h: number
}

const nodePositions = computed<Map<string, NodePosition>>(() => {
  const map = new Map<string, NodePosition>()
  if (!props.nodes.length) return map

  // 按 depth 分组
  const byDepth = new Map<number, ExecutionNode[]>()
  for (const n of props.nodes) {
    const list = byDepth.get(n.depth) || []
    list.push(n)
    byDepth.set(n.depth, list)
  }

  const maxDepth = Math.max(...byDepth.keys(), 0)

  for (const [depth, nodesAtDepth] of byDepth) {
    nodesAtDepth.forEach((node, idx) => {
      const totalAtDepth = nodesAtDepth.length
      const x = CANVAS_PADDING + depth * DEPTH_OFFSET_X
      const y = CANVAS_PADDING + idx * (NODE_H + NODE_GAP_Y)
        - (totalAtDepth - 1) * (NODE_H + NODE_GAP_Y) / 2
        + 300 // 垂直居中偏移
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

// ==================== 边路径计算 ====================
function edgePath(from: NodePosition, to: NodePosition): string {
  const startX = from.x + from.w
  const startY = from.y + from.h / 2
  const endX = to.x
  const endY = to.y + to.h / 2
  const midX = (startX + endX) / 2
  return `M ${startX},${startY} C ${midX},${startY} ${midX},${endY} ${endX},${endY}`
}

// ==================== 状态颜色映射 ====================
const STATUS_COLORS: Record<string, { fill: string; stroke: string; text: string }> = {
  pending:   { fill: 'rgba(99, 99, 102, 0.12)', stroke: 'rgba(120, 120, 128, 0.35)', text: '#636366' },
  running:   { fill: 'rgba(10, 132, 255, 0.13)', stroke: 'rgba(10, 132, 255, 0.55)', text: '#64d2ff' },
  completed: { fill: 'rgba(48, 209, 88, 0.1)', stroke: 'rgba(48, 209, 88, 0.3)', text: '#4db86b' },
  failed:    { fill: 'rgba(255, 69, 58, 0.1)', stroke: 'rgba(255, 69, 58, 0.55)', text: '#ff6961' },
  cancelled: { fill: 'rgba(240, 162, 69, 0.1)', stroke: 'rgba(240, 162, 69, 0.4)', text: '#f0a245' },
  timeout:   { fill: 'rgba(240, 162, 69, 0.14)', stroke: 'rgba(240, 162, 69, 0.6)', text: '#f0a245' },
  interrupted: { fill: 'rgba(118, 118, 128, 0.1)', stroke: 'rgba(118, 118, 128, 0.4)', text: '#8e8e93' },
}

function colorFor(node: ExecutionNode) {
  return STATUS_COLORS[node.status] || STATUS_COLORS.pending
}

const statusLabel: Record<string, string> = {
  pending: '等待中', running: '运行中', completed: '已完成',
  failed: '失败', cancelled: '已取消', timeout: '超时', interrupted: '已中断',
}

// ==================== 交互 ====================
function onNodeClick(nodeId: string) {
  emit('selectNode', nodeId)
}

function onSvgMouseDown(e: MouseEvent) {
  if (e.target === svgRef.value || (e.target as Element).classList.contains('svg-bg')) {
    isDragging.value = true
    dragStart.value = { x: e.clientX, y: e.clientY }
    vbStart.value = { ...viewBox.value }
  }
}

function onSvgMouseMove(e: MouseEvent) {
  if (!isDragging.value) return
  const dx = (e.clientX - dragStart.value.x) * viewBox.value.w / (svgRef.value?.clientWidth ?? 800)
  const dy = (e.clientY - dragStart.value.y) * viewBox.value.h / (svgRef.value?.clientHeight ?? 600)
  viewBox.value.x = vbStart.value.x - dx
  viewBox.value.y = vbStart.value.y - dy
}

function onSvgMouseUp() {
  isDragging.value = false
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  const factor = e.deltaY > 0 ? 1.15 : 0.87
  viewBox.value.w *= factor
  viewBox.value.h *= factor
}

function fitView() {
  viewBox.value = { x: -20, y: -20, w: svgSize.value.w + 40, h: svgSize.value.h + 40 }
}

function selectNodeFromEvent(e: CustomEvent) {
  emit('selectNode', e.detail.nodeId)
}

// 初始化 viewBox
watch(
  () => props.nodes.length,
  () => { fitView() },
  { immediate: true },
)

onMounted(() => {
  document.addEventListener('keydown', handleKey)
  window.addEventListener('resize', fitView)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKey)
  window.removeEventListener('resize', fitView)
})

function handleKey(e: KeyboardEvent) {
  if (e.key === 'f' || e.key === 'F') { fitView(); e.preventDefault() }
  if (e.key === '+' || e.key === '=') { viewBox.value.w *= 0.9; viewBox.value.h *= 0.9; e.preventDefault() }
  if (e.key === '-') { viewBox.value.w *= 1.1; viewBox.value.h *= 1.1; e.preventDefault() }
}

defineExpose({ fitView })
</script>

<template>
  <div class="graph-container">
    <svg
      ref="svgRef"
      :viewBox="`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`"
      class="graph-svg"
      @mousedown="onSvgMouseDown"
      @mousemove="onSvgMouseMove"
      @mouseup="onSvgMouseUp"
      @mouseleave="onSvgMouseUp"
      @wheel="onWheel"
      @selectNode="selectNodeFromEvent"
    >
      <!-- 背景 -->
      <rect class="svg-bg" :x="viewBox.x" :y="viewBox.y" :width="viewBox.w" :height="viewBox.h" fill="transparent" />

      <!-- 边 -->
      <g class="edges-layer">
        <path
          v-for="edge in edges"
          :key="`${edge.from}-${edge.to}`"
          v-show="nodePositions.has(edge.from) && nodePositions.has(edge.to)"
          :d="edgePath(nodePositions.get(edge.from)!, nodePositions.get(edge.to)!)"
          class="graph-edge"
          fill="none"
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
          @click.stop="onNodeClick(node.id)"
        >
          <!-- 节点背景 -->
          <rect
            :x="0"
            :y="0"
            :width="NODE_W"
            :height="NODE_H"
            :rx="10"
            :fill="colorFor(node).fill"
            :stroke="colorFor(node).stroke"
            :stroke-width="selectedNodeId === node.id ? 2 : (node.status === 'failed' ? 2 : 1)"
            class="node-rect"
          />

          <!-- 运行中脉冲动画 -->
          <rect
            v-if="node.status === 'running'"
            :x="-2"
            :y="-2"
            :width="NODE_W + 4"
            :height="NODE_H + 4"
            :rx="12"
            fill="none"
            :stroke="colorFor(node).stroke"
            stroke-width="1.5"
            stroke-dasharray="4 2"
            class="node-pulse"
          />

          <!-- 错误标记 -->
          <NodeErrorOverlay
            v-if="node.hasError"
            :node-id="node.id"
            :x="NODE_W - 16"
            :y="-4"
          />

          <!-- 节点类型图标 -->
          <text :x="12" :y="22" class="node-type-icon">
            {{ node.type === 'orchestrator' ? '◇' : '◆' }}
          </text>

          <!-- 节点名称 -->
          <text :x="30" :y="22" class="node-name" :fill="colorFor(node).text">
            {{ node.name.length > 14 ? node.name.slice(0, 13) + '…' : node.name }}
          </text>

          <!-- 副标题 -->
          <text :x="12" :y="40" class="node-sub" fill="var(--tertiary)">
            {{ node.sub.length > 20 ? node.sub.slice(0, 19) + '…' : node.sub }}
          </text>

          <!-- 状态和计时 -->
          <text :x="12" :y="54" class="node-status" :fill="colorFor(node).text">
            {{ statusLabel[node.status] || node.status }}
            <tspan v-if="node.durationMs != null" fill="var(--tertiary)">
              · {{ (node.durationMs / 1000).toFixed(1) }}s
            </tspan>
          </text>

          <!-- 工具调用计数徽章 -->
          <g v-if="node.hasToolCalls" :transform="`translate(${NODE_W - 28}, 42)`">
            <rect :x="0" :y="0" width="22" height="14" rx="7" fill="rgba(10, 132, 255, 0.15)" />
            <text :x="11" :y="10" text-anchor="middle" class="tool-badge-text">🔧{{ node.toolCallCount }}</text>
          </g>
        </g>
      </g>
    </svg>

    <!-- 缩放控件 -->
    <div class="graph-controls">
      <button type="button" title="适应画布 (F)" @click="fitView">⊡</button>
      <button type="button" title="放大 (+)" @click="viewBox.w *= 0.9; viewBox.h *= 0.9">+</button>
      <button type="button" title="缩小 (-)" @click="viewBox.w *= 1.1; viewBox.h *= 1.1">−</button>
    </div>
  </div>
</template>

<style scoped>
.graph-container {
  flex: 1;
  min-height: 0;
  position: relative;
  background: rgba(0, 0, 0, 0.12);
  border-radius: 10px;
  border: 1px solid var(--separator-soft);
  overflow: hidden;
}

.graph-svg {
  width: 100%;
  height: 100%;
  cursor: grab;
}

.graph-svg:active {
  cursor: grabbing;
}

/* 边样式 */
.graph-edge {
  stroke: var(--separator-soft);
  stroke-width: 1.5;
  transition: stroke 0.3s;
}

/* 节点样式 */
.graph-node {
  cursor: pointer;
  transition: transform 0.15s ease;
}

.graph-node:hover {
  filter: brightness(1.1);
}

.graph-node:hover .node-rect {
  stroke-width: 2;
}

.node-selected .node-rect {
  filter: brightness(1.15);
}

/* 脉冲动画 */
.node-pulse {
  animation: pulse-ring 1.8s ease-in-out infinite;
  opacity: 0;
}

@keyframes pulse-ring {
  0%   { opacity: 0.6; stroke-dashoffset: 0; }
  50%  { opacity: 0.2; stroke-dashoffset: 20; }
  100% { opacity: 0.6; stroke-dashoffset: 40; }
}

/* 文本样式 */
.node-type-icon {
  font-size: 0.6rem;
  fill: var(--blue);
  font-weight: 600;
}

.node-name {
  font-size: 0.5625rem;
  font-weight: 600;
}

.node-sub {
  font-size: 0.4375rem;
  overflow: hidden;
}

.node-status {
  font-size: 0.4375rem;
}

.tool-badge-text {
  font-size: 0.375rem;
  fill: #64d2ff;
}

/* 缩放控件 */
.graph-controls {
  position: absolute;
  bottom: 8px;
  right: 8px;
  display: flex;
  gap: 3px;
}

.graph-controls button {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: 6px;
  background: rgba(44, 44, 46, 0.85);
  color: var(--secondary);
  font-size: 0.7rem;
  cursor: pointer;
  backdrop-filter: blur(12px);
  border: 1px solid var(--separator-soft);
}

.graph-controls button:hover {
  background: rgba(44, 44, 46, 0.95);
  color: var(--label);
}
</style>
