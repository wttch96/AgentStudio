<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { ActiveAgent } from '../types'

const props = defineProps<{
  submitting: boolean
  autofocus?: boolean
  isRunning: boolean
  queueItems: { id: string; objective: string }[]
  activeAgents: ActiveAgent[]
  activeRunId: string | null
}>()
const emit = defineEmits<{
  submit: [objective: string]
  interrupt: []
  promoteQueue: [qid: string]
  removeQueue: [qid: string]
  interruptAgent: [agent: string, action: string, instruction?: string]
}>()

const objective = ref('')
const input = ref<HTMLTextAreaElement | null>(null)
const showInterruptMenu = ref(false)
const showInjectPopup = ref(false)
const injectTarget = ref('all')
const injectInstruction = ref('')

const commandOptions = [
  { command: '/+', label: '执行预定义流程 (用法: /+流程名)', isFlow: true },
  { command: '/agent', label: '指定 Agent 并传递引导指令 (用法: /agent <名称> <指令>)' },
  { command: '/frontend', label: '快捷引导 vue-frontend' },
  { command: '/backend', label: '快捷引导 flask-backend' },
  { command: '/retry', label: '重试失败节点（后接 task-id）' },
]
// Flow names for /+ auto-completion
import { api } from '../api/client'
import type { FlowDefinition } from '../types'
const flowOptions = ref<Array<{ command: string; label: string; isFlow: boolean }>>([])
const loadingFlows = ref(false)

async function fetchFlows() {
  if (loadingFlows.value) return
  loadingFlows.value = true
  try {
    const items = await api.flows()
    flowOptions.value = items.map((f: FlowDefinition) => ({
      command: `/+${f.name}`,
      label: `${f.description} (v${f.version}, ${f.node_count || '?'} 节点)`,
      isFlow: true,
    }))
  } catch {
    flowOptions.value = []
  } finally {
    loadingFlows.value = false
  }
}
const visibleCommands = computed(() => {
  const value = objective.value.trim().toLowerCase()
  if (!value.startsWith('/') || value.includes(' ')) return []
  // Fetch flows when user types /+
  if (value.startsWith('/+')) {
    fetchFlows()
    return flowOptions.value.filter((item) => item.command.startsWith(value))
  }
  return commandOptions.filter((item) => item.command.startsWith(value))
})

async function submit() {
  const value = objective.value.trim()
  if (!value || props.submitting) return
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

function handleInterruptAction(agent: string, action: string) {
  if (action === 'inject') {
    injectTarget.value = agent
    showInjectPopup.value = true
    showInterruptMenu.value = false
    return
  }
  emit('interruptAgent', agent, action)
  showInterruptMenu.value = false
}

function sendInjectInstruction() {
  if (!injectInstruction.value.trim()) return
  emit('interruptAgent', injectTarget.value, 'inject', injectInstruction.value.trim())
  injectInstruction.value = ''
  showInjectPopup.value = false
}

function closeInterruptMenu() {
  showInterruptMenu.value = false
}

// Close interrupt menu on click outside
function onInterruptBlur(event: FocusEvent) {
  // Small delay to allow click on menu items
  setTimeout(() => {
    if (showInterruptMenu.value) showInterruptMenu.value = false
  }, 150)
}

defineExpose({ focus })
</script>

<template>
  <div class="composer-shell">
    <!-- Command menu -->
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
      <div class="queue-header">
        <span>待执行队列 ({{ queueItems.length }})</span>
        <small>点击 ↑ 优先执行 · 点击 × 移除</small>
      </div>
      <div v-for="q in queueItems" :key="q.id" class="queue-item">
        <span class="queue-index">{{ queueItems.indexOf(q) + 1 }}</span>
        <span class="queue-text">{{ q.objective.slice(0, 80) }}{{ q.objective.length > 80 ? '…' : '' }}</span>
        <div class="queue-actions">
          <button type="button" class="queue-btn promote" title="优先执行" @click="$emit('promoteQueue', q.id)">↑</button>
          <button type="button" class="queue-btn remove" title="移除" @click="$emit('removeQueue', q.id)">×</button>
        </div>
      </div>
    </div>

    <!-- Inject instruction popup -->
    <div v-if="showInjectPopup" class="inject-popup">
      <div class="inject-popup-header">
        <strong>
          注入指令到 {{ injectTarget === 'all' ? '全部 Agent' : injectTarget }}
        </strong>
        <button type="button" class="inject-close" @click="showInjectPopup = false">×</button>
      </div>
      <textarea
        v-model="injectInstruction"
        rows="3"
        placeholder="输入引导指令…"
        class="inject-textarea"
        @keydown.enter.exact.prevent="sendInjectInstruction"
      />
      <div class="inject-actions">
        <button type="button" class="inject-cancel" @click="showInjectPopup = false">取消</button>
        <button
          type="button"
          class="inject-send"
          :disabled="!injectInstruction.trim()"
          @click="sendInjectInstruction"
        >发送指令</button>
      </div>
    </div>

    <!-- Textarea -->
    <textarea
      ref="input"
      v-model="objective"
      rows="3"
      maxlength="20000"
      :placeholder="isRunning ? '任务执行中，输入引导指令加入队列…' : '描述你希望多个 Agent 完成的任务…'"
      aria-label="任务目标"
      @keydown="handleKeydown"
    />

    <!-- Toolbar -->
    <div class="composer-toolbar">
      <div class="composer-hint">
        <template v-if="isRunning">
          <span class="running-dot" />
          任务执行中 · {{ activeAgents.length }} 个 Agent 活跃
        </template>
        <template v-else>
          <kbd>/</kbd> 选择 Agent · <kbd>Enter</kbd> 发送
        </template>
      </div>

      <div class="composer-actions">
        <!-- Interrupt dropdown -->
        <div v-if="isRunning" class="interrupt-wrapper">
          <button
            class="interrupt-button"
            type="button"
            @click="showInterruptMenu = !showInterruptMenu"
            @blur="onInterruptBlur"
          >
            中断 <span aria-hidden="true">▼</span>
          </button>
          <div v-if="showInterruptMenu" class="interrupt-menu">
            <div class="interrupt-section-label">暂停执行</div>
            <button type="button" @click="handleInterruptAction('all', 'pause')">
              <span class="interrupt-icon">⏸</span> 暂停全部 Agent
            </button>
            <button
              v-for="agent in activeAgents"
              :key="agent.name"
              type="button"
              @click="handleInterruptAction(agent.name, 'pause')"
            >
              <span class="interrupt-icon">⏸</span> 暂停 {{ agent.name }}
              <small>{{ agent.title }}</small>
            </button>

            <div class="interrupt-divider" />

            <div class="interrupt-section-label">注入指令</div>
            <button type="button" @click="handleInterruptAction('all', 'inject')">
              <span class="interrupt-icon">💬</span> 注入指令到全部 Agent
            </button>
            <button
              v-for="agent in activeAgents"
              :key="'inj-' + agent.name"
              type="button"
              @click="handleInterruptAction(agent.name, 'inject')"
            >
              <span class="interrupt-icon">💬</span> 注入指令到 {{ agent.name }}
            </button>

            <div class="interrupt-divider" />

            <div class="interrupt-section-label">其他</div>
            <button type="button" @click="handleInterruptAction('all', 'replan')">
              <span class="interrupt-icon">🔄</span> 触发重规划
            </button>
            <button type="button" class="interrupt-abort" @click="$emit('interrupt'); showInterruptMenu = false">
              <span class="interrupt-icon">⏹</span> 中止运行
            </button>
          </div>
        </div>

        <!-- Send button -->
        <button
          class="send-button"
          type="button"
          :disabled="!objective.trim() || submitting"
          @click="submit"
        >
          {{ submitting ? '创建中' : isRunning ? '加入队列' : '运行' }}
          <span aria-hidden="true">↑</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Inject popup */
.inject-popup {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin-bottom: 0.5rem;
  padding: 0.75rem;
  background: var(--surface-raised);
  border: 1px solid var(--separator);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  z-index: 10;
}

.inject-popup-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.inject-popup-header strong {
  font-size: 0.7rem;
  color: var(--label);
}

.inject-close {
  background: none;
  border: 0;
  color: var(--secondary);
  cursor: pointer;
  font-size: 1rem;
  padding: 0;
  line-height: 1;
}

.inject-textarea {
  width: 100%;
  border: 1px solid var(--separator-soft);
  border-radius: 8px;
  padding: 0.5rem;
  background: var(--surface);
  color: var(--label);
  font-size: 0.7rem;
  resize: vertical;
  outline: none;
  font-family: inherit;
}

.inject-textarea:focus {
  border-color: var(--blue);
}

.inject-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.inject-cancel {
  border: 1px solid var(--separator-soft);
  border-radius: 7px;
  padding: 0.35rem 0.7rem;
  background: transparent;
  color: var(--secondary);
  cursor: pointer;
  font-size: 0.65rem;
}

.inject-cancel:hover {
  background: var(--surface-hover);
}

.inject-send {
  border: 0;
  border-radius: 7px;
  padding: 0.35rem 0.7rem;
  background: var(--blue);
  color: #fff;
  cursor: pointer;
  font-size: 0.65rem;
  font-weight: 600;
}

.inject-send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Queue list */
.queue-list {
  margin-bottom: 0.5rem;
}

.queue-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.35rem;
}

.queue-header span {
  font-size: 0.6rem;
  color: var(--secondary);
  font-weight: 600;
}

.queue-header small {
  font-size: 0.5rem;
  color: var(--tertiary);
}

.queue-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.5rem;
  border-radius: 7px;
  background: var(--surface-raised);
  margin-bottom: 0.25rem;
  border: 1px solid var(--separator-soft);
}

.queue-index {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--blue-soft);
  color: #64d2ff;
  font-size: 0.55rem;
  font-weight: 700;
  flex-shrink: 0;
}

.queue-text {
  flex: 1;
  min-width: 0;
  font-size: 0.65rem;
  color: var(--label);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-actions {
  display: flex;
  gap: 0.2rem;
  flex-shrink: 0;
}

.queue-btn {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.7rem;
  line-height: 1;
}

.queue-btn.promote {
  background: rgba(10, 132, 255, 0.12);
  color: #64d2ff;
}

.queue-btn.promote:hover {
  background: rgba(10, 132, 255, 0.22);
}

.queue-btn.remove {
  background: rgba(255, 69, 58, 0.1);
  color: var(--red);
}

.queue-btn.remove:hover {
  background: rgba(255, 69, 58, 0.2);
}

/* Composer actions */
.composer-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* Interrupt dropdown */
.interrupt-wrapper {
  position: relative;
}

.interrupt-button {
  border: 0;
  border-radius: 8px;
  padding: 0.45rem 0.65rem;
  background: rgba(255, 69, 58, 0.14);
  color: #ff6961;
  cursor: pointer;
  font-size: 0.65rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.interrupt-button:hover {
  background: rgba(255, 69, 58, 0.22);
}

.interrupt-button span {
  font-size: 0.45rem;
}

.interrupt-menu {
  position: absolute;
  bottom: 100%;
  right: 0;
  margin-bottom: 0.35rem;
  min-width: 240px;
  background: var(--surface-raised);
  border: 1px solid var(--separator);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  overflow: hidden;
  z-index: 20;
}

.interrupt-section-label {
  padding: 0.4rem 0.7rem;
  font-size: 0.5rem;
  font-weight: 650;
  color: var(--tertiary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.interrupt-menu button {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  border: 0;
  padding: 0.45rem 0.7rem;
  background: transparent;
  color: var(--label);
  cursor: pointer;
  font-size: 0.7rem;
  text-align: left;
}

.interrupt-menu button:hover {
  background: var(--surface-hover);
}

.interrupt-menu button small {
  color: var(--tertiary);
  font-size: 0.55rem;
  margin-left: auto;
}

.interrupt-icon {
  font-size: 0.7rem;
  width: 18px;
  text-align: center;
}

.interrupt-divider {
  height: 1px;
  background: var(--separator-soft);
  margin: 0.2rem 0;
}

.interrupt-abort {
  color: #ff6961 !important;
}

.composer-hint .running-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--blue);
  display: inline-block;
  margin-right: 0.25rem;
  animation: pulse-dot 1.5s ease-in-out infinite;
  vertical-align: middle;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}
</style>
