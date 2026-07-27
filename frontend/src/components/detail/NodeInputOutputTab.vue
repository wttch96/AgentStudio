<script setup lang="ts">
import { computed } from 'vue'
import type { ExecutionNode } from '../../types'

const props = defineProps<{
  node: ExecutionNode
}>()

const isLLMPrompt = computed(() => {
  const input = props.node.input as Record<string, unknown> | null
  return input?.llmPrompt != null
})

const llmPrompt = computed(() => {
  const input = props.node.input as Record<string, unknown> | null
  return input?.llmPrompt as {
    system_prompt: string
    user_prompt: string
    model: string
    duration_ms: number
  } | null
})

const formattedInput = computed(() => {
  if (!props.node.input) return null
  if (isLLMPrompt.value) return null
  try {
    return JSON.stringify(props.node.input, null, 2)
  } catch {
    return String(props.node.input)
  }
})

const formattedOutput = computed(() => {
  if (!props.node.output) return null
  try {
    return JSON.stringify(props.node.output, null, 2)
  } catch {
    return String(props.node.output)
  }
})

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}
</script>

<template>
  <div class="io-tab">
    <template v-if="isLLMPrompt && llmPrompt">
      <div class="io-section">
        <h3 class="io-heading">
          <span class="io-badge in">IN</span>
          完整 LLM 输入
          <span class="io-meta">模型: {{ llmPrompt.model }} · 耗时: {{ formatDuration(llmPrompt.duration_ms) }}</span>
        </h3>
        <details class="prompt-section" open>
          <summary class="prompt-summary">
            <span class="prompt-label system">SYSTEM</span>
            系统提示词
          </summary>
          <pre class="io-pre">{{ llmPrompt.system_prompt }}</pre>
        </details>
        <details class="prompt-section" open>
          <summary class="prompt-summary">
            <span class="prompt-label user">USER</span>
            用户消息
          </summary>
          <pre class="io-pre">{{ llmPrompt.user_prompt }}</pre>
        </details>
      </div>
    </template>
    <template v-else>
      <div class="io-section">
        <h3 class="io-heading">
          <span class="io-badge in">IN</span>
          输入
        </h3>
        <pre v-if="formattedInput" class="io-pre">{{ formattedInput }}</pre>
        <p v-else class="io-empty">— 无输入数据 —</p>
      </div>
    </template>
    <div class="io-section">
      <h3 class="io-heading">
        <span class="io-badge out">OUT</span>
        输出
      </h3>
      <pre v-if="formattedOutput" class="io-pre">{{ formattedOutput }}</pre>
      <p v-else class="io-empty">
        {{ node.status === 'running' ? '— 等待执行完成… —' : '— 无输出数据 —' }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.io-tab {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.io-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.io-heading {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: var(--ui-font-md);
  font-weight: 650;
  color: var(--secondary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.io-meta {
  font-size: var(--ui-font-sm);
  font-weight: 400;
  color: var(--tertiary);
  text-transform: none;
  letter-spacing: 0;
  margin-left: 8px;
}

.io-badge {
  font-size: var(--ui-font-sm);
  font-weight: 700;
  padding: 2px 5px;
  border-radius: 3px;
}

.io-badge.in {
  background: rgba(10, 132, 255, 0.15);
  color: #64d2ff;
}

.io-badge.out {
  background: rgba(48, 209, 88, 0.15);
  color: var(--green);
}

.prompt-section {
  margin-bottom: 8px;
}

.prompt-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 6px 0;
  font-size: var(--ui-font-md);
  color: var(--secondary);
  user-select: none;
}

.prompt-label {
  font-size: var(--ui-font-xs);
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  letter-spacing: 0.04em;
}

.prompt-label.system {
  background: rgba(255, 159, 10, 0.18);
  color: #ff9f0a;
}

.prompt-label.user {
  background: rgba(10, 132, 255, 0.18);
  color: #64d2ff;
}

.io-pre {
  margin: 0;
  padding: 10px;
  border-radius: 8px;
  background: #111113;
  color: rgba(235, 235, 245, 0.76);
  font: var(--ui-font-base) / 1.55 ui-monospace, 'SFMono-Regular', Menlo, monospace;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid var(--separator-soft);
}

.io-empty {
  margin: 0;
  font-size: var(--ui-font-md);
  color: var(--tertiary);
  font-style: italic;
  padding: 8px 0;
}
</style>
