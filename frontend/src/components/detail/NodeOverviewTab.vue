<script setup lang="ts">
import { computed } from 'vue'
import type { ExecutionNode } from '../../types'

const props = defineProps<{
  node: ExecutionNode
}>()

const statusLabel: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  timeout: '超时',
  interrupted: '已中断',
}

const typeLabel: Record<string, string> = {
  conversation: '对话轮次',
  orchestrator: '主脑编排',
  agent: '执行 Agent',
}

const elapsed = computed(() => {
  if (props.node.startedAt && props.node.finishedAt) {
    const ms = new Date(props.node.finishedAt).getTime() - new Date(props.node.startedAt).getTime()
    return `${(ms / 1000).toFixed(1)}s`
  }
  if (props.node.durationMs != null) {
    return `${(props.node.durationMs / 1000).toFixed(1)}s`
  }
  if (props.node.startedAt && props.node.status === 'running') {
    const ms = Date.now() - new Date(props.node.startedAt).getTime()
    return `${(ms / 1000).toFixed(0)}s (进行中)`
  }
  return '—'
})

const formattedStartedAt = computed(() => {
  if (!props.node.startedAt) return '—'
  return new Date(props.node.startedAt).toLocaleTimeString()
})

const formattedFinishedAt = computed(() => {
  if (!props.node.finishedAt) return props.node.status === 'running' ? '运行中…' : '—'
  return new Date(props.node.finishedAt).toLocaleTimeString()
})

function formatTokens(value: number) {
  if (value < 1000) return String(value)
  return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}k`
}
</script>

<template>
  <div class="overview-tab">
    <!-- 状态 + 类型 -->
    <div class="overview-section">
      <div class="overview-row">
        <span class="overview-label">类型</span>
        <span class="overview-value type-badge">{{ typeLabel[node.type] || node.type }}</span>
      </div>
      <div class="overview-row">
        <span class="overview-label">状态</span>
        <span class="overview-value" :class="`status-${node.status}`">
          <span class="status-indicator" />{{ statusLabel[node.status] || node.status }}
        </span>
      </div>
      <div v-if="node.agentId" class="overview-row">
        <span class="overview-label">Agent</span>
        <span class="overview-value mono">{{ node.agentId }}</span>
      </div>
    </div>

    <!-- 耗时 -->
    <div class="overview-section">
      <h3 class="section-title">耗时</h3>
      <div class="overview-row">
        <span class="overview-label">耗时</span>
        <span class="overview-value">{{ elapsed }}</span>
      </div>
      <div class="overview-row">
        <span class="overview-label">开始</span>
        <span class="overview-value time">{{ formattedStartedAt }}</span>
      </div>
      <div class="overview-row">
        <span class="overview-label">结束</span>
        <span class="overview-value time">{{ formattedFinishedAt }}</span>
      </div>
    </div>

    <!-- 目标 -->
    <div v-if="node.objective" class="overview-section">
      <h3 class="section-title">任务目标</h3>
      <p class="overview-objective">{{ node.objective }}</p>
    </div>

    <!-- 摘要 -->
    <div v-if="node.summary" class="overview-section">
      <h3 class="section-title">输出摘要</h3>
      <p class="overview-summary">{{ node.summary }}</p>
    </div>

    <!-- 状态信息 -->
    <div class="overview-section">
      <h3 class="section-title">
        Token I/O
        <span v-if="node.tokenUsage.estimated" class="estimate-badge">估算</span>
      </h3>
      <div class="overview-metrics">
        <div class="metric token-input">
          <span class="metric-value">{{ formatTokens(node.tokenUsage.input) }}</span>
          <span class="metric-label">输入 Token</span>
        </div>
        <div class="metric token-output">
          <span class="metric-value">{{ formatTokens(node.tokenUsage.output) }}</span>
          <span class="metric-label">输出 Token</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ formatTokens(node.tokenUsage.input + node.tokenUsage.output) }}</span>
          <span class="metric-label">合计</span>
        </div>
      </div>
    </div>

    <div class="overview-section">
      <h3 class="section-title">节点统计</h3>
      <div class="overview-metrics">
        <div class="metric">
          <span class="metric-value">{{ node.toolCallCount }}</span>
          <span class="metric-label">工具调用</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ node.intermediateSteps.length }}</span>
          <span class="metric-label">中间步骤</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ node.dependsOn.length }}</span>
          <span class="metric-label">依赖项</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overview-tab {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.overview-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-title {
  margin: 0;
  font-size: var(--ui-font-md);
  font-weight: 650;
  color: var(--secondary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.estimate-badge {
  margin-left: 5px;
  padding: 1px 5px;
  border-radius: 999px;
  background: rgba(255, 159, 10, 0.14);
  color: var(--orange);
  font-size: var(--ui-font-xs);
  font-weight: 600;
  letter-spacing: 0;
  text-transform: none;
}

.token-input .metric-value { color: #64d2ff; }
.token-output .metric-value { color: var(--green); }

.overview-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 3px 0;
}

.overview-label {
  font-size: var(--ui-font-md);
  color: var(--tertiary);
  flex-shrink: 0;
}

.overview-value {
  font-size: var(--ui-font-md);
  font-weight: 500;
  text-align: right;
}

.overview-value.mono {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: var(--ui-font-base);
}

.overview-value.time {
  color: var(--tertiary);
  font-size: var(--ui-font-base);
}

.type-badge {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--blue-soft);
  color: var(--blue);
  font-size: var(--ui-font-base);
}

/* 状态颜色 */
.overview-value.status-running { color: #64d2ff; }
.overview-value.status-completed { color: var(--green); }
.overview-value.status-failed { color: var(--red); }
.overview-value.status-timeout { color: var(--orange); }
.overview-value.status-interrupted { color: var(--tertiary); }
.overview-value.status-pending { color: var(--tertiary); }

.status-indicator {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  margin-right: 5px;
  vertical-align: middle;
}

.status-running .status-indicator { background: var(--blue); }
.status-completed .status-indicator { background: var(--green); }
.status-failed .status-indicator { background: var(--red); }
.status-timeout .status-indicator { background: var(--orange); }
.status-interrupted .status-indicator { background: #8e8e93; }
.status-pending .status-indicator { background: #636366; }

.overview-objective,
.overview-summary {
  margin: 0;
  font-size: var(--ui-font-md);
  line-height: 1.5;
  color: var(--secondary);
  white-space: pre-wrap;
}

/* 指标卡片 */
.overview-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 8px 4px;
  border-radius: 8px;
  background: rgba(44, 44, 46, 0.5);
  border: 1px solid var(--separator-soft);
}

.metric-value {
  font-size: var(--ui-font-base);
  font-weight: 650;
  color: var(--label);
}

.metric-label {
  font-size: var(--ui-font-sm);
  color: var(--tertiary);
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
</style>
