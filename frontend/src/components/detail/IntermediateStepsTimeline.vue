<script setup lang="ts">
import { computed } from 'vue'
import type { IntermediateStep } from '../types'

defineProps<{
  steps: IntermediateStep[]
}>()

const STEP_ICONS: Record<string, string> = {
  thought: '💭',
  action: '🔧',
  observation: '👁',
  message: '💬',
}

const STEP_LABELS: Record<string, string> = {
  thought: '推理',
  action: '行动',
  observation: '观察',
  message: '消息',
}

const STEP_COLORS: Record<string, string> = {
  thought: '#da8fff',
  action: '#64d2ff',
  observation: '#f0a245',
  message: '#4db86b',
}
</script>

<template>
  <div class="steps-timeline">
    <!-- 空状态 -->
    <div v-if="!steps.length" class="steps-empty">
      <p>— 无中间步骤 —</p>
      <p class="steps-hint">待后端补充: agent.thinking 事件可提供更细粒度的推理步骤</p>
    </div>

    <!-- 时间线 -->
    <div v-else class="steps-list">
      <div
        v-for="step in steps"
        :key="step.id"
        class="step-item"
      >
        <!-- 时间线连接线 + 节点 -->
        <div class="step-marker">
          <div class="step-line" />
          <span
            class="step-dot"
            :style="{ background: STEP_COLORS[step.type] || '#636366' }"
          >
            {{ STEP_ICONS[step.type] || '·' }}
          </span>
        </div>

        <!-- 内容 -->
        <div class="step-content">
          <div class="step-head">
            <span class="step-type" :style="{ color: STEP_COLORS[step.type] || 'var(--tertiary)' }">
              {{ STEP_LABELS[step.type] || step.type }}
            </span>
            <span class="step-time">{{ new Date(step.timestamp).toLocaleTimeString() }}</span>
          </div>
          <p class="step-text">{{ step.content.slice(0, 500) }}</p>

          <!-- 行动的行内工具信息 -->
          <div v-if="step.action" class="step-action-info">
            <code>{{ step.action.tool }}</code>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.steps-timeline {
  display: flex;
  flex-direction: column;
}

.steps-empty {
  text-align: center;
  padding: 20px 0;
}

.steps-empty p {
  font-size: 0.5625rem;
  color: var(--tertiary);
  font-style: italic;
  margin: 0;
}

.steps-hint {
  font-size: 0.4375rem !important;
  color: var(--tertiary) !important;
  margin-top: 8px !important;
  font-style: normal !important;
  opacity: 0.6;
}

.steps-list {
  display: flex;
  flex-direction: column;
}

.step-item {
  display: flex;
  gap: 10px;
  padding-bottom: 12px;
  position: relative;
}

.step-item:last-child .step-line {
  display: none;
}

.step-marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  width: 20px;
}

.step-line {
  flex: 1;
  width: 1px;
  background: var(--separator-soft);
  min-height: 12px;
}

.step-dot {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  font-size: 0.5625rem;
  flex-shrink: 0;
}

.step-content {
  flex: 1;
  min-width: 0;
  padding-top: 1px;
}

.step-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.step-type {
  font-size: 0.5rem;
  font-weight: 650;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.step-time {
  font-size: 0.4375rem;
  color: var(--tertiary);
  white-space: nowrap;
}

.step-text {
  margin: 4px 0 0;
  font-size: 0.5625rem;
  line-height: 1.5;
  color: var(--secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.step-action-info {
  margin-top: 4px;
}

.step-action-info code {
  font-size: 0.4375rem;
  padding: 2px 5px;
  border-radius: 3px;
  background: rgba(10, 132, 255, 0.1);
  color: #64d2ff;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
}
</style>
