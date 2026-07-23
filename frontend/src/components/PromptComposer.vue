<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'

const props = defineProps<{
  submitting: boolean
  autofocus?: boolean
  isRunning: boolean
  queueItems: { id: string; objective: string }[]
}>()
const emit = defineEmits<{
  submit: [objective: string]
  interrupt: []
  promoteQueue: [qid: string]
  removeQueue: [qid: string]
}>()

const objective = ref('')
const input = ref<HTMLTextAreaElement | null>(null)
const commandOptions = [
  { command: '/agent', label: '指定 Agent 并传递引导指令 (用法: /agent <名称> <指令>)' },
  { command: '/frontend', label: '快捷引导 vue-frontend' },
  { command: '/backend', label: '快捷引导 flask-backend' },
  { command: '/retry', label: '重试失败节点（后接 task-id）' },
]
const visibleCommands = computed(() => {
  const value = objective.value.trim().toLowerCase()
  if (!value.startsWith('/') || value.includes(' ')) return []
  return commandOptions.filter((item) => item.command.startsWith(value))
})

async function submit() {
  const value = objective.value.trim()
  if (!value || props.submitting || props.disabled) return
  emit('submit', value)
  objective.value = ''
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void submit()
  }
}

async function focus() {
  await nextTick()
  input.value?.focus()
}

async function chooseCommand(command: string) {
  objective.value = `${command} `
  await focus()
}

defineExpose({ focus })
</script>

<template>
  <div class="composer-shell">
    <div v-if="visibleCommands.length" class="command-menu">
      <button
        v-for="item in visibleCommands"
        :key="item.command"
        type="button"
        @click="chooseCommand(item.command)"
      >
        <strong>{{ item.command }}</strong>
        <span>{{ item.label }}</span>
      </button>
    </div>
    <!-- 任务队列 -->
    <div v-if="queueItems.length" class="queue-list">
      <div class="queue-header"><span>待执行队列 ({{ queueItems.length }})</span><small>点击条目可优先执行</small></div>
      <div v-for="q in queueItems" :key="q.id" class="queue-item">
        <span class="queue-text">{{ q.objective.slice(0, 80) }}{{ q.objective.length > 80 ? '…' : '' }}</span>
        <div class="queue-actions">
          <button type="button" class="queue-btn promote" title="优先执行" @click="$emit('promoteQueue', q.id)">↑</button>
          <button type="button" class="queue-btn remove" title="移除" @click="$emit('removeQueue', q.id)">×</button>
        </div>
      </div>
    </div>
    <textarea
      ref="input"
      v-model="objective"
      rows="3"
      maxlength="20000"
      :placeholder="isRunning ? '任务执行中，输入引导指令…' : '描述你希望多个 Agent 完成的任务…'"
      aria-label="任务目标"
      @keydown="handleKeydown"
    />
    <div class="composer-toolbar">
      <div class="composer-hint">
        <template v-if="isRunning"><span class="running-dot" /> 任务执行中，输入引导指令注入当前任务</template>
        <template v-else><kbd>/</kbd> 选择 Agent · <kbd>Enter</kbd> 发送</template>
      </div>
      <button
        v-if="isRunning"
        class="stop-button"
        type="button"
        title="中断当前任务并执行队列中的下一条"
        @click="$emit('interrupt')"
      >
        中断 <span aria-hidden="true">■</span>
      </button>
      <button
        class="send-button"
        type="button"
        :disabled="!objective.trim() || submitting"
        @click="submit"
      >
        {{ submitting ? '创建中' : '运行' }}
        <span aria-hidden="true">↑</span>
      </button>
    </div>
  </div>
</template>
