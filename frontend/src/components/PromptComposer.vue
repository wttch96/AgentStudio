<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'

const props = defineProps<{
  submitting: boolean
  continuing: boolean
  disabled: boolean
  autofocus?: boolean
}>()
const emit = defineEmits<{ submit: [objective: string] }>()

const objective = ref('')
const input = ref<HTMLTextAreaElement | null>(null)
const commandOptions = [
  { command: '/frontend', label: '直接选择 frontend-agent' },
  { command: '/backend', label: '直接选择 backend-agent' },
  { command: '/netty', label: '直接选择 netty-agent' },
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
    <textarea
      ref="input"
      v-model="objective"
      rows="3"
      maxlength="20000"
      :placeholder="continuing ? '基于上游输出继续说明，例如：按刚才方案开始修改…' : '描述你希望多个 Agent 完成的任务…'"
      aria-label="任务目标"
      :disabled="disabled"
      @keydown="handleKeydown"
    />
    <div class="composer-toolbar">
      <div class="composer-hint">
        <template v-if="disabled">等待当前任务结束后可继续</template>
        <template v-else-if="continuing"><span class="continuation-dot" /> 将携带上游输出继续</template>
        <template v-else><kbd>/</kbd> 选择 Agent · <kbd>Enter</kbd> 发送</template>
      </div>
      <button
        class="send-button"
        type="button"
        :disabled="!objective.trim() || submitting || disabled"
        @click="submit"
      >
        {{ submitting ? '创建中' : continuing ? '继续' : '运行' }}
        <span aria-hidden="true">↑</span>
      </button>
    </div>
  </div>
</template>
