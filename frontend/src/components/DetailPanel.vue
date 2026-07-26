<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import NodeOverviewTab from './detail/NodeOverviewTab.vue'
import NodeInputOutputTab from './detail/NodeInputOutputTab.vue'
import ToolCallsTimeline from './detail/ToolCallsTimeline.vue'
import IntermediateStepsTimeline from './detail/IntermediateStepsTimeline.vue'
import NodeErrorView from './detail/NodeErrorView.vue'
import NodeActionBar from './detail/NodeActionBar.vue'
import type { ExecutionNode, ToolCallGroup, IntermediateStep, TaskError } from '../types'

const props = defineProps<{
  selectedNode: ExecutionNode | null
  isRunning: boolean
}>()

const emit = defineEmits<{
  close: []
  interruptNode: [nodeId: string]
}>()

type TabId = 'overview' | 'io' | 'tools' | 'steps' | 'errors'

const tabs: Array<{ id: TabId; label: string }> = [
  { id: 'overview', label: '概览' },
  { id: 'io', label: 'I/O' },
  { id: 'tools', label: '工具' },
  { id: 'steps', label: '步骤' },
  { id: 'errors', label: '错误' },
]

const activeTab = ref<TabId>('overview')

// 当选中节点变化时重置 tab
watch(
  () => props.selectedNode?.id,
  () => { activeTab.value = 'overview' },
)

const hasTools = computed(() => (props.selectedNode?.toolCallGroups?.length ?? 0) > 0)
const hasSteps = computed(() => (props.selectedNode?.intermediateSteps?.length ?? 0) > 0)
const hasError = computed(() => props.selectedNode?.hasError ?? false)
</script>

<template>
  <aside class="detail-panel" :class="{ 'detail-empty': !selectedNode }">
    <!-- 空状态 -->
    <template v-if="!selectedNode">
      <div class="detail-empty-state">
        <div class="detail-empty-icon">◇</div>
        <p>点击画布中的节点查看详情</p>
      </div>
    </template>

    <!-- 有选中节点 -->
    <template v-else>
      <!-- 头部：节点名称 + 关闭/中断按钮 -->
      <div class="detail-header">
        <div class="detail-header-info">
          <span
            class="detail-status-dot"
            :class="`dot-${selectedNode.status}`"
          />
          <div class="detail-header-text">
            <strong>{{ selectedNode.name }}</strong>
            <span>{{ (selectedNode.sub || '').slice(0, 40) }}</span>
          </div>
        </div>
        <div class="detail-header-actions">
          <NodeActionBar
            v-if="['pending', 'running'].includes(selectedNode.status) && selectedNode.interruptible"
            :node-id="selectedNode.id"
            :node-name="selectedNode.name"
            @interrupt="(id) => emit('interruptNode', id)"
          />
          <ElButton text circle class="detail-close-btn" title="关闭" @click="emit('close')">×</ElButton>
        </div>
      </div>

      <ElTabs v-model="activeTab" class="detail-tabs">
        <ElTabPane
          v-for="tab in tabs"
          :key="tab.id"
          :name="tab.id"
          :disabled="(tab.id === 'tools' && !hasTools)
            || (tab.id === 'steps' && !hasSteps)
            || (tab.id === 'errors' && !hasError)"
        >
          <template #label>
            {{ tab.label }}
            <span v-if="tab.id === 'tools' && hasTools" class="tab-badge">{{ selectedNode.toolCallCount }}</span>
            <span v-if="tab.id === 'errors' && hasError" class="tab-badge error">!</span>
          </template>
          <div class="detail-content">
            <NodeOverviewTab v-if="tab.id === 'overview'" :node="selectedNode" />
            <NodeInputOutputTab v-else-if="tab.id === 'io'" :node="selectedNode" />
            <ToolCallsTimeline v-else-if="tab.id === 'tools'" :tool-call-groups="selectedNode.toolCallGroups" />
            <IntermediateStepsTimeline v-else-if="tab.id === 'steps'" :steps="selectedNode.intermediateSteps" />
            <NodeErrorView v-else-if="tab.id === 'errors'" :error="selectedNode.error" />
          </div>
        </ElTabPane>
      </ElTabs>
    </template>
  </aside>
</template>

<style scoped>
.detail-panel {
  width: 340px;
  min-width: 340px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--sidebar);
  backdrop-filter: saturate(160%) blur(30px);
  border-left: 1px solid var(--separator-soft);
  overflow: hidden;
}

.detail-empty {
  display: flex;
  align-items: center;
  justify-content: center;
}

.detail-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--tertiary);
  text-align: center;
  padding: 2rem;
}

.detail-empty-icon {
  font-size: 2rem;
  opacity: 0.25;
}

.detail-empty-state p {
  font-size: var(--ui-font-md);
  line-height: 1.5;
}

/* 头部 */
.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 14px 12px 10px;
  border-bottom: 1px solid var(--separator-soft);
  flex-shrink: 0;
}

.detail-header-info {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.detail-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 4px;
  flex-shrink: 0;
  background: #636366;
}

.detail-status-dot.dot-running { background: var(--blue); box-shadow: 0 0 0 3px rgba(10,132,255,.15); }
.detail-status-dot.dot-completed { background: var(--green); }
.detail-status-dot.dot-failed { background: var(--red); }
.detail-status-dot.dot-timeout { background: var(--orange); }
.detail-status-dot.dot-interrupted { background: #8e8e93; }

.detail-header-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.detail-header-text strong {
  font-size: var(--ui-font-lg);
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-header-text span {
  font-size: var(--ui-font-base);
  color: var(--secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.detail-close-btn {
  width: 24px;
  height: 24px;
  background: rgba(118, 118, 128, 0.12);
  color: var(--secondary);
  font-size: var(--ui-font-md);
}

.detail-close-btn:hover {
  background: rgba(255, 69, 58, 0.14);
  color: var(--red);
}

/* Tab 导航 */
.detail-tabs {
  flex: 1;
  min-height: 0;
  background: rgba(0, 0, 0, 0.08);
}

.detail-tabs :deep(.el-tabs__header) {
  flex: none;
  margin: 0;
  padding: 0 8px;
  border-bottom: 1px solid var(--separator-soft);
}
.detail-tabs :deep(.el-tabs__nav-wrap::after) {
  background: transparent;
}
.detail-tabs :deep(.el-tabs__item) {
  height: 36px;
  padding: 0 10px;
  font-size: var(--ui-font-sm);
}
.detail-tabs :deep(.el-tabs__content) {
  height: calc(100% - 37px);
  min-height: 0;
  overflow: hidden;
}
.detail-tabs :deep(.el-tab-pane) {
  height: 100%;
}

.tab-badge {
  font-size: var(--ui-font-xs);
  padding: 1px 4px;
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.15);
  color: #64d2ff;
}

.tab-badge.error {
  background: rgba(255, 69, 58, 0.15);
  color: #ff6961;
}

/* 内容区 */
.detail-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
}
</style>
