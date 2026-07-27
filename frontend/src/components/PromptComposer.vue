<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ActiveAgent, AgentProfile } from '../types'

const props = defineProps<{
  submitting: boolean; autofocus?: boolean; isRunning: boolean
  isAwaitingConfirmation?: boolean
  queueItems: { id: string; objective: string }[]
  activeAgents: ActiveAgent[]; activeRunId: string | null
  agents: AgentProfile[]
}>()
const emit = defineEmits<{
  submit: [objective: string, mode?: string]; interrupt: []
  promoteQueue: [qid: string]; removeQueue: [qid: string]
  interruptAgent: [agent: string, action: string, instruction?: string]
  confirmExecute: []
  chatRefine: [message: string]
}>()

const objective = ref('')
const input = ref<InstanceType<typeof HTMLTextAreaElement> | any>(null)
const showInterruptMenu = ref(false)
const isComposing = ref(false)
const activeCommandIndex = ref(0)
const commandMenu = ref<HTMLElement | null>(null)
const interruptBtn = ref<HTMLElement | null>(null)
const interruptMenu = ref<HTMLElement | null>(null)
const runMode = ref<'auto' | 'interactive'>('auto')

const commandOptions = computed(() => [
  { command: '/brain', label: props.isRunning ? '引导主脑并按需重规划' : '由主脑规划任务' },
  ...props.agents.map(a => ({
    command: `/${a.name}`, label: `引导 ${a.display_name || a.name}`,
  })),
])

const visibleCommands = computed(() => {
  const value = objective.value.toLowerCase()
  if (!value.startsWith('/') || /\s/.test(value)) return []
  return commandOptions.value.filter(i => i.command.startsWith(value))
})

watch(objective, () => {
  activeCommandIndex.value = 0
})

watch(visibleCommands, (commands) => {
  if (!commands.length) {
    activeCommandIndex.value = 0
  } else if (activeCommandIndex.value >= commands.length) {
    activeCommandIndex.value = commands.length - 1
  }
})

async function submit() {
  const value = objective.value.trim()
  if (!value || props.submitting) return
  emit('submit', value, runMode.value); objective.value = ''
}

function toggleRunMode() {
  runMode.value = runMode.value === 'auto' ? 'interactive' : 'auto'
}

async function moveCommand(delta: number) {
  const count = visibleCommands.value.length
  if (!count) return
  activeCommandIndex.value = (activeCommandIndex.value + delta + count) % count
  await nextTick()
  commandMenu.value
    ?.querySelector<HTMLElement>('.command-option.selected')
    ?.scrollIntoView({ block: 'nearest' })
}

function handleKeydown(event: KeyboardEvent) {
  const composing = isComposing.value || event.isComposing || event.keyCode === 229
  if (composing) return

  if (visibleCommands.value.length) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      void moveCommand(1)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      void moveCommand(-1)
      return
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      void chooseCommand(visibleCommands.value[activeCommandIndex.value].command)
      return
    }
  }

  if (
    event.key === 'Enter'
    && (event.ctrlKey || event.metaKey)
  ) {
    event.preventDefault()
    void submit()
  }
}
function handleCompositionStart() { isComposing.value = true }
function handleCompositionEnd() { isComposing.value = false }
async function focus() { await nextTick(); input.value?.focus() }
async function chooseCommand(command: string) { objective.value = `${command} `; await focus() }
defineExpose({ focus })

function handleInterruptAction(agent: string, action: string) {
  emit('interruptAgent', agent, action); showInterruptMenu.value = false
}

// 点击外部关闭中断菜单
function onClickOutside(e: MouseEvent) {
  if (!showInterruptMenu.value) return
  const target = e.target as HTMLElement
  if (interruptBtn.value?.contains(target)) return
  if (!interruptMenu.value?.contains(target)) {
    showInterruptMenu.value = false
  }
}

onMounted(() => document.addEventListener('mousedown', onClickOutside, true))
onBeforeUnmount(() => document.removeEventListener('mousedown', onClickOutside, true))

function toggleInterruptMenu() {
  showInterruptMenu.value = !showInterruptMenu.value
}
</script>

<template>
  <div class="border-top bg-body-tertiary p-2 position-relative">
    <!-- Queue -->
    <div v-if="queueItems.length" class="mb-1">
      <div class="d-flex justify-content-between small text-secondary mb-1">
        <span>待执行队列 ({{ queueItems.length }})</span>
        <span>点击 ↑ 优先 · × 移除</span>
      </div>
      <div v-for="q in queueItems" :key="q.id" class="d-flex align-items-center gap-2 p-1 border rounded mb-1 small bg-body">
        <ElTag type="info" size="small" round>{{ queueItems.indexOf(q) + 1 }}</ElTag>
        <span class="flex-grow-1 text-truncate">{{ q.objective.slice(0, 80) }}</span>
        <ElButton link size="small" class="p-0 text-primary" title="优先" @click="$emit('promoteQueue', q.id)">&#8593;</ElButton>
        <ElButton link size="small" class="p-0 text-danger" title="移除" @click="$emit('removeQueue', q.id)">&times;</ElButton>
      </div>
    </div>

    <!-- Textarea + slash command menu -->
    <div class="prompt-input-wrap mb-1">
      <div
        v-if="visibleCommands.length"
        ref="commandMenu"
        class="command-menu"
        role="listbox"
        aria-label="命令建议"
        :aria-activedescendant="`command-option-${activeCommandIndex}`"
      >
        <ElButton
          v-for="(item, index) in visibleCommands"
          :id="`command-option-${index}`"
          :key="item.command"
          link
          size="small"
          role="option"
          class="command-option"
          :class="{ selected: index === activeCommandIndex }"
          :aria-selected="index === activeCommandIndex"
          @mouseenter="activeCommandIndex = index"
          @click="chooseCommand(item.command)"
        >
          <strong>{{ item.command }}</strong>
          <small>{{ item.label }}</small>
        </ElButton>
        <div class="command-menu-hint">
          <kbd>↑</kbd><kbd>↓</kbd> 选择
          <kbd>Tab</kbd> 补全
        </div>
      </div>

      <ElInput
        ref="input"
        v-model="objective"
        type="textarea"
        :rows="3"
        maxlength="20000"
        :placeholder="isAwaitingConfirmation ? '输入修改意见完善计划，或直接点击「确认执行」…' : isRunning ? '使用 /brain 或 /<agent-name> 引导；普通输入加入队列…' : '描述任务，或使用 / 选择主脑/Agent…'"
        aria-label="任务目标"
        @keydown="handleKeydown"
        @compositionstart="handleCompositionStart"
        @compositionend="handleCompositionEnd"
      />
    </div>

    <!-- Toolbar -->
    <div class="d-flex justify-content-between align-items-center">
      <div class="small text-secondary">
        <template v-if="isAwaitingConfirmation">
          <span class="d-inline-block rounded-circle bg-warning me-1" style="width:7px;height:7px;animation:pulse-dot 1.5s ease-in-out infinite" />
          计划已生成 · 请确认或修改后执行
        </template>
        <template v-else-if="isRunning">
          <span class="d-inline-block rounded-circle bg-primary me-1" style="width:7px;height:7px;animation:pulse-dot 1.5s ease-in-out infinite" />
          任务执行中 · {{ activeAgents.length }} 个 Agent 活跃
        </template>
        <template v-else>
          <kbd>/</kbd> 选择 Agent · <kbd>Enter</kbd> 换行 · <kbd>⌘/Ctrl + Enter</kbd> 发送
          <ElButton
            size="small"
            :type="runMode === 'interactive' ? 'warning' : 'info'"
            plain
            class="ms-2"
            style="font-size:11px;padding:1px 7px;"
            @click="toggleRunMode"
          >
            {{ runMode === 'interactive' ? '🔍 先规划' : '⚡ 直接执行' }}
          </ElButton>
        </template>
      </div>

      <div class="d-flex gap-1">
        <!-- 确认模式操作栏 -->
        <template v-if="isAwaitingConfirmation">
          <ElButton type="warning" size="small" plain @click="showInterruptMenu = !showInterruptMenu">取消</ElButton>
          <ElButton size="small" @click="() => { const msg = objective.trim(); if (msg) { emit('chatRefine', msg); objective = '' } }" :disabled="!objective.trim()">发送修改建议</ElButton>
          <ElButton type="success" size="small" @click="$emit('confirmExecute')">确认执行 &#9654;</ElButton>
        </template>
        <!-- 中断 -->
        <template v-else-if="isRunning">
        <div class="position-relative">
          <ElButton ref="interruptBtn" type="danger" size="small" plain @mousedown.prevent="toggleInterruptMenu">中断</ElButton>
          <div v-if="showInterruptMenu" ref="interruptMenu" class="position-absolute bottom-100 end-0 mb-1 bg-body border rounded shadow-sm" style="min-width:220px;z-index:20">
            <div class="px-2 py-1 small text-secondary">暂停执行</div>
            <ElButton link size="small" class="d-block w-100 text-start" @mousedown.prevent="handleInterruptAction('all', 'pause')">&#9208; 暂停全部 Agent</ElButton>
            <ElButton v-for="a in activeAgents" :key="a.name" link size="small" class="d-block w-100 text-start" @mousedown.prevent="handleInterruptAction(a.name, 'pause')">
              &#9208; 暂停 {{ a.name }} <small class="text-secondary">{{ a.title }}</small>
            </ElButton>
            <hr class="my-1" />
            <ElButton link size="small" class="d-block w-100 text-start" @mousedown.prevent="handleInterruptAction('all', 'replan')">&#128260; 触发重规划</ElButton>
            <ElButton type="danger" size="small" class="d-block w-100" @mousedown.prevent="$emit('interrupt'); showInterruptMenu = false">&#9209; 中止运行</ElButton>
          </div>
          </div>
        </template>
        <ElButton type="primary" size="small" :disabled="!objective.trim() || submitting" @click="submit">
          {{ submitting ? '创建中…' : isAwaitingConfirmation ? '加入队列 ▲' : isRunning ? '加入队列 ▲' : '运行 ▲' }}
        </ElButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }

.prompt-input-wrap {
  position: relative;
}

.command-menu {
  position: absolute;
  right: 0;
  bottom: calc(100% + 6px);
  left: 0;
  z-index: 30;
  max-height: min(320px, 45vh);
  overflow-x: hidden;
  overflow-y: auto;
  padding: 4px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
  background: var(--el-bg-color-overlay);
  box-shadow: var(--el-box-shadow-light);
}

.command-option {
  display: flex;
  width: 100%;
  height: 32px;
  margin: 0;
  justify-content: flex-start;
  gap: 8px;
  padding: 0 10px;
  border-radius: var(--el-border-radius-small);
  color: var(--el-text-color-primary);
}

.command-option + .command-option {
  margin-left: 0;
}

.command-option:hover,
.command-option.selected {
  background: var(--el-fill-color-light);
  color: var(--el-color-primary);
}

.command-option small {
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-menu-hint {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  padding: 4px 8px 2px;
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-xs);
}
</style>
