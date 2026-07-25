<script setup lang="ts">
import { computed } from 'vue'
import type { ExecutionNode } from '../types'

const props = defineProps<{
  node: ExecutionNode
}>()

const formattedInput = computed(() => {
  if (!props.node.input) return null
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
</script>

<template>
  <div class="io-tab">
    <!-- 输入 -->
    <div class="io-section">
      <h3 class="io-heading">
        <span class="io-badge in">IN</span>
        输入
      </h3>
      <pre v-if="formattedInput" class="io-pre">{{ formattedInput }}</pre>
      <p v-else class="io-empty">— 无输入数据 —</p>
    </div>

    <!-- 输出 -->
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
  font-size: 0.9375rem;
  font-weight: 650;
  color: var(--secondary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.io-badge {
  font-size: 0.8125rem;
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

.io-pre {
  margin: 0;
  padding: 10px;
  border-radius: 8px;
  background: #111113;
  color: rgba(235, 235, 245, 0.76);
  font: 0.875rem / 1.55 ui-monospace, 'SFMono-Regular', Menlo, monospace;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid var(--separator-soft);
}

.io-empty {
  margin: 0;
  font-size: 0.9375rem;
  color: var(--tertiary);
  font-style: italic;
  padding: 8px 0;
}
</style>
