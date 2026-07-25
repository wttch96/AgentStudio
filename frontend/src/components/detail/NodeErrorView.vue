<script setup lang="ts">
import { ref } from 'vue'
import type { TaskError } from '../types'

defineProps<{
  error: TaskError | null
}>()

const showStack = ref(false)

const ERROR_ICONS: Record<string, string> = {
  EXCEPTION: '✕',
  TIMEOUT: '⏱',
  USER_CANCEL: '⊘',
  UNKNOWN: '?',
}

const ERROR_COLORS: Record<string, string> = {
  EXCEPTION: 'var(--red)',
  TIMEOUT: 'var(--orange)',
  USER_CANCEL: '#8e8e93',
  UNKNOWN: '#8e8e93',
}

const ERROR_LABELS: Record<string, string> = {
  EXCEPTION: '执行异常',
  TIMEOUT: '执行超时',
  USER_CANCEL: '用户取消',
  UNKNOWN: '未知错误',
}
</script>

<template>
  <div class="error-view">
    <!-- 无错误 -->
    <div v-if="!error" class="error-none">
      <p>✓ 该节点无错误</p>
    </div>

    <!-- 有错误 -->
    <template v-else>
      <!-- 错误类型徽章 -->
      <div class="error-header">
        <span
          class="error-type-badge"
          :style="{ background: (ERROR_COLORS[error.type] || ERROR_COLORS.UNKNOWN) + '18', color: ERROR_COLORS[error.type] || ERROR_COLORS.UNKNOWN, borderColor: (ERROR_COLORS[error.type] || ERROR_COLORS.UNKNOWN) + '30' }"
        >
          {{ ERROR_ICONS[error.type] || ERROR_ICONS.UNKNOWN }}
          {{ ERROR_LABELS[error.type] || ERROR_LABELS.UNKNOWN }}
        </span>
      </div>

      <!-- 错误摘要 -->
      <div class="error-summary-section">
        <h3 class="error-section-title">错误摘要</h3>
        <p class="error-message">{{ error.message }}</p>
      </div>

      <!-- 堆栈跟踪（可折叠） -->
      <div class="error-stack-section">
        <h3 class="error-section-title" style="display:flex;justify-content:space-between;align-items:center;">
          堆栈跟踪
          <button
            v-if="error.stack"
            type="button"
            class="error-toggle-btn"
            @click="showStack = !showStack"
          >
            {{ showStack ? '收起' : '展开' }}
          </button>
        </h3>
        <div v-if="error.stack && showStack">
          <pre class="error-stack">{{ error.stack }}</pre>
        </div>
        <p v-else-if="!error.stack" class="error-stack-hint">
          待后端补充：结构化堆栈跟踪信息
          <br/>当前后端仅返回 "TypeName: message" 格式的错误文本
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.error-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.error-none {
  text-align: center;
  padding: 20px 0;
}

.error-none p {
  margin: 0;
  font-size: 0.9375rem;
  color: var(--green);
}

.error-header {
  display: flex;
  align-items: center;
}

.error-type-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid;
  font-size: 0.9375rem;
  font-weight: 650;
}

.error-section-title {
  margin: 0 0 6px;
  font-size: 0.9375rem;
  font-weight: 650;
  color: var(--secondary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.error-message {
  margin: 0;
  font-size: 0.9375rem;
  line-height: 1.5;
  color: var(--label);
  padding: 8px;
  border-radius: 7px;
  background: rgba(255, 69, 58, 0.08);
  border: 1px solid rgba(255, 69, 58, 0.15);
  white-space: pre-wrap;
  word-break: break-word;
}

.error-stack {
  margin: 0;
  padding: 10px;
  border-radius: 7px;
  background: #111113;
  color: rgba(235, 235, 245, 0.7);
  font: 0.8125rem / 1.5 ui-monospace, 'SFMono-Regular', Menlo, monospace;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
  border: 1px solid var(--separator-soft);
}

.error-stack-hint {
  font-size: 0.875rem;
  color: var(--tertiary);
  line-height: 1.5;
  font-style: italic;
  margin: 0;
}

.error-toggle-btn {
  border: 0;
  border-radius: 4px;
  padding: 2px 6px;
  background: rgba(118, 118, 128, 0.12);
  color: var(--secondary);
  font-size: 0.875rem;
  cursor: pointer;
}

.error-toggle-btn:hover {
  background: rgba(118, 118, 128, 0.22);
  color: var(--label);
}
</style>
