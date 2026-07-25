<script setup lang="ts">
import { computed } from 'vue'
import NodeGraphCanvas from './NodeGraphCanvas.vue'
import NodeFilterBar from './NodeFilterBar.vue'
import type { ExecutionNode, NodeEdge, NodeStatus } from '../types'

const props = defineProps<{
  nodes: ExecutionNode[]
  edges: NodeEdge[]
  selectedNodeId: string | null
  filterStatus: NodeStatus | 'all'
  isRunning: boolean
  activeRunObjective: string
  streamingThinking: string
  streamingResponse: string
  isStreaming: boolean
}>()

const emit = defineEmits<{
  selectNode: [nodeId: string]
  interruptNode: [nodeId: string]
  updateFilter: [status: NodeStatus | 'all']
  toggleDagModal: []
}>()

const filteredNodes = computed(() => {
  if (props.filterStatus === 'all') return props.nodes
  return props.nodes.filter((n) => n.status === props.filterStatus)
})

const errorCount = computed(() => props.nodes.filter((n) => n.hasError).length)
const runningCount = computed(() => props.nodes.filter((n) => n.status === 'running').length)
</script>

<template>
  <div class="main-canvas">
    <!-- 运行状态栏 -->
    <div v-if="isRunning" class="canvas-status-bar">
      <div class="status-bar-left">
        <span class="status-bar-pulse" />
        <span class="status-bar-text">
          {{ activeRunObjective.slice(0, 80) }}{{ activeRunObjective.length > 80 ? '…' : '' }}
        </span>
      </div>
      <div class="status-bar-right">
        <span v-if="runningCount" class="status-bar-badge running">{{ runningCount }} 运行中</span>
        <span v-if="errorCount" class="status-bar-badge error">{{ errorCount }} 错误</span>
        <button type="button" class="dag-trigger-btn" @click="emit('toggleDagModal')" title="全屏 DAG 视图">
          <span aria-hidden="true">◇</span> DAG
        </button>
      </div>
    </div>

    <!-- 流式内容提示 -->
    <div v-if="isStreaming && streamingThinking" class="canvas-streaming-hint">
      <span class="streaming-dot" />
      <span class="streaming-text">{{ streamingThinking.slice(-120) }}</span>
    </div>

    <!-- 筛选栏 -->
    <NodeFilterBar
      :filter-status="filterStatus"
      :counts="{
        all: nodes.length,
        running: nodes.filter(n => n.status === 'running').length,
        completed: nodes.filter(n => n.status === 'completed').length,
        failed: nodes.filter(n => n.status === 'failed').length,
      }"
      @update-filter="(s) => emit('updateFilter', s)"
    />

    <!-- 主画布 -->
    <NodeGraphCanvas
      :nodes="filteredNodes"
      :edges="edges"
      :selected-node-id="selectedNodeId"
      :filter-status="filterStatus"
      @select-node="(id) => emit('selectNode', id)"
      @interrupt-node="(id) => emit('interruptNode', id)"
    />

    <!-- 空状态 -->
    <div v-if="!nodes.length && !isRunning" class="canvas-empty">
      <div class="canvas-empty-icon">◇</div>
      <p>选择一个任务或创建一个新任务来查看执行图</p>
    </div>

    <!-- 等待规划中 -->
    <div v-if="!nodes.length && isRunning" class="canvas-empty">
      <div class="canvas-empty-icon pulsing">◇</div>
      <p>主脑正在分析目标并生成执行计划…</p>
    </div>
  </div>
</template>

<style scoped>
.main-canvas {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
  position: relative;
  overflow: hidden;
  padding: 0.5rem 0.75rem 0.25rem;
}

/* 状态栏 */
.canvas-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  padding: 6px 10px;
  margin-bottom: 6px;
  border-radius: 9px;
  background: rgba(10, 132, 255, 0.07);
  border: 1px solid rgba(10, 132, 255, 0.15);
}

.status-bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.status-bar-pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--blue);
  flex-shrink: 0;
  animation: status-pulse 1.2s ease-in-out infinite;
}

@keyframes status-pulse {
  50% { box-shadow: 0 0 8px 3px rgba(10, 132, 255, 0.3); }
}

.status-bar-text {
  font-size: 0.625rem;
  color: var(--secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-bar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.status-bar-badge {
  font-size: 0.5rem;
  padding: 2px 6px;
  border-radius: 999px;
  font-weight: 600;
}

.status-bar-badge.running {
  background: rgba(10, 132, 255, 0.15);
  color: #64d2ff;
}

.status-bar-badge.error {
  background: rgba(255, 69, 58, 0.15);
  color: #ff6961;
}

.dag-trigger-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid rgba(10, 132, 255, 0.25);
  border-radius: 7px;
  background: rgba(10, 132, 255, 0.08);
  color: #64d2ff;
  font-size: 0.625rem;
  font-weight: 550;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.dag-trigger-btn:hover {
  background: rgba(10, 132, 255, 0.16);
  border-color: rgba(10, 132, 255, 0.45);
}

/* 流式提示 */
.canvas-streaming-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  margin-bottom: 6px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.03);
  flex-shrink: 0;
}

.streaming-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--green);
  flex-shrink: 0;
  animation: status-pulse 0.8s ease-in-out infinite;
}

.streaming-text {
  font-size: 0.5625rem;
  color: var(--tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 空状态 */
.canvas-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  gap: 12px;
  color: var(--tertiary);
}

.canvas-empty-icon {
  font-size: 2rem;
  opacity: 0.3;
}

.canvas-empty-icon.pulsing {
  animation: empty-pulse 2s ease-in-out infinite;
}

@keyframes empty-pulse {
  50% { opacity: 0.6; transform: scale(1.1); }
}

.canvas-empty p {
  font-size: 0.6875rem;
  max-width: 280px;
  text-align: center;
  line-height: 1.5;
}
</style>
