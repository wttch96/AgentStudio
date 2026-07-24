<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { ConversationTurn, StreamingState } from '../types'

const props = defineProps<{
  turns: ConversationTurn[]
  streaming: StreamingState
  activeRunId: string | null
  isRunning: boolean
}>()

const emit = defineEmits<{
  interrupt: []
  fork: [runId: string]
}>()

const chatScroll = ref<HTMLElement | null>(null)
const thinkingCollapsed = ref<Set<string>>(new Set())
const responseCollapsed = ref<Set<string>>(new Set())

function toggleThinking(turnId: string) {
  const next = new Set(thinkingCollapsed.value)
  if (next.has(turnId)) next.delete(turnId)
  else next.add(turnId)
  thinkingCollapsed.value = next
}

function toggleResponse(turnId: string) {
  const next = new Set(responseCollapsed.value)
  if (next.has(turnId)) next.delete(turnId)
  else next.add(turnId)
  responseCollapsed.value = next
}

function formatTime(ts: string): string {
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    thinking: '思考中',
    executing: '执行中',
    responding: '响应中',
    complete: '完成',
    error: '失败',
  }
  return map[status] || status
}

function statusClass(status: string): string {
  return status === 'error' ? 'error' : status === 'complete' ? 'complete' : 'active'
}

const displayTurns = computed(() => {
  return props.turns.slice().reverse()
})

// Auto-scroll to bottom when new turns or streaming text arrives
watch(
  () => [props.turns.length, props.streaming.responseText, props.streaming.thinkingText],
  async () => {
    await nextTick()
    if (chatScroll.value) {
      chatScroll.value.scrollTop = chatScroll.value.scrollHeight
    }
  },
  { deep: false },
)

onMounted(async () => {
  await nextTick()
  if (chatScroll.value) {
    chatScroll.value.scrollTop = chatScroll.value.scrollHeight
  }
})
</script>

<template>
  <div class="streaming-chat">
    <div ref="chatScroll" class="chat-scroll">
      <!-- Empty state -->
      <div v-if="displayTurns.length === 0 && !isRunning" class="chat-empty">
        <div class="chat-empty-icon">&#x1F4AC;</div>
        <h3>开始对话</h3>
        <p>在下方输入目标，主脑将调度 Agent 团队执行。</p>
      </div>

      <!-- Conversation turns -->
      <template v-for="turn in displayTurns" :key="turn.id">
        <div
          class="chat-turn"
          :class="{ active: turn.runId === activeRunId }"
        >
          <!-- User message -->
          <div class="chat-msg user">
            <div class="msg-avatar" aria-hidden="true">U</div>
            <div class="msg-content">
              <div class="msg-bubble user-bubble">
                <div class="msg-text">{{ turn.userMessage }}</div>
              </div>
              <div class="msg-meta">
                <span>{{ formatTime(turn.createdAt) }}</span>
                <span :class="'status-badge ' + statusClass(turn.status)">
                  {{ statusLabel(turn.status) }}
                </span>
                <button
                  v-if="turn.status === 'complete'"
                  type="button"
                  class="fork-btn"
                  title="分叉此对话"
                  @click="emit('fork', turn.runId)"
                >⎇ 分叉</button>
              </div>
            </div>
          </div>

          <!-- Thinking section (collapsible) -->
          <div v-if="turn.thinkingText" class="chat-msg brain">
            <div class="msg-avatar brain-avatar" aria-hidden="true">B</div>
            <div class="msg-content">
              <div
                class="thinking-toggle"
                @click="toggleThinking(turn.id)"
                role="button"
                :aria-expanded="!thinkingCollapsed.has(turn.id)"
              >
                <span class="thinking-icon">{{ thinkingCollapsed.has(turn.id) ? '&#x25B6;' : '&#x25BC;' }}</span>
                <span class="thinking-label">思考过程</span>
                <span v-if="turn.planTasks.length" class="thinking-badge">
                  {{ turn.planTasks.length }} 个任务
                </span>
                <span v-if="turn.status === 'thinking' && turn.runId === activeRunId" class="thinking-pulse" />
              </div>
              <div v-if="!thinkingCollapsed.has(turn.id)" class="thinking-body">
                <pre class="thinking-text">{{ turn.thinkingText }}</pre>
                <div v-if="turn.planTasks.length" class="plan-summary">
                  <span class="plan-summary-label">任务列表:</span>
                  <div v-for="t in turn.planTasks" :key="t.id" class="plan-task-chip">
                    <span class="plan-task-agent">{{ t.agent }}</span>
                    <span>{{ t.title }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Brain response -->
          <div v-if="turn.brainResponse || (turn.runId === activeRunId && isRunning)" class="chat-msg brain">
            <div class="msg-avatar brain-avatar" aria-hidden="true">B</div>
            <div class="msg-content">
              <div
                v-if="turn.brainResponse"
                class="response-toggle"
                @click="toggleResponse(turn.id)"
                role="button"
                :aria-expanded="!responseCollapsed.has(turn.id)"
              >
                <span class="thinking-icon">{{ responseCollapsed.has(turn.id) ? '&#x25B6;' : '&#x25BC;' }}</span>
                <span class="thinking-label">主脑响应</span>
              </div>
              <div v-if="!responseCollapsed.has(turn.id) && turn.brainResponse" class="msg-bubble brain-bubble">
                <div class="msg-text response-text">{{ turn.brainResponse }}</div>
              </div>
              <!-- Streaming indicator for active turn -->
              <div
                v-if="turn.runId === activeRunId && isRunning && !turn.brainResponse"
                class="msg-bubble brain-bubble streaming-bubble"
              >
                <div v-if="streaming.thinkingText" class="streaming-thinking">
                  {{ streaming.thinkingText }}
                </div>
                <div v-if="streaming.responseText" class="streaming-response">
                  {{ streaming.responseText }}
                </div>
                <div v-if="!streaming.thinkingText && !streaming.responseText" class="streaming-wait">
                  <span class="wait-dot" /> 等待主脑响应…
                </div>
                <span class="typing-cursor" v-if="streaming.isStreaming">|</span>
              </div>
            </div>
          </div>

          <!-- Memory compaction for this turn -->
          <div v-if="turn.memoryEvents.length" class="chat-msg system">
            <div class="msg-avatar sys-avatar" aria-hidden="true">M</div>
            <div class="msg-content">
              <div class="memory-mini">
                <span class="memory-icon">&#x1F9E0;</span>
                <span>
                  {{ turn.memoryEvents.length }} 次记忆压缩 ·
                  最后压缩: Wave {{ turn.memoryEvents[turn.memoryEvents.length - 1].wave }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Active streaming: thinking only (no turn yet for queued state) -->
      <div v-if="isRunning && activeRunId && displayTurns.length === 0" class="chat-msg brain">
        <div class="msg-avatar brain-avatar" aria-hidden="true">B</div>
        <div class="msg-content">
          <div class="msg-bubble brain-bubble streaming-bubble">
            <div v-if="streaming.thinkingText">{{ streaming.thinkingText }}</div>
            <div v-else><span class="wait-dot" /> 主脑规划中…</div>
            <span class="typing-cursor" v-if="streaming.isStreaming">|</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.streaming-chat {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  max-width: var(--content-width);
  margin: 0 auto;
  width: 100%;
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  scroll-behavior: smooth;
}

/* Empty state */
.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 2rem;
  text-align: center;
  color: var(--secondary);
}

.chat-empty-icon {
  font-size: 2.5rem;
  margin-bottom: 0.75rem;
  opacity: 0.6;
}

.chat-empty h3 {
  margin: 0 0 0.35rem;
  font-size: 1rem;
  font-weight: 600;
  color: var(--label);
}

.chat-empty p {
  margin: 0;
  font-size: 0.75rem;
}

/* Turn */
.chat-turn {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.4rem 0;
}

/* Messages */
.chat-msg {
  display: flex;
  gap: 0.6rem;
  align-items: flex-start;
}

.msg-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 700;
  flex-shrink: 0;
}

.user .msg-avatar {
  background: var(--blue);
  color: #fff;
}

.brain .msg-avatar,
.brain-avatar {
  background: linear-gradient(145deg, #48484a, #2c2c2e);
  color: var(--label);
}

.system .msg-avatar,
.sys-avatar {
  background: rgba(191, 90, 242, 0.18);
  color: #da8fff;
}

.msg-content {
  flex: 1;
  min-width: 0;
}

.msg-bubble {
  padding: 0.6rem 0.85rem;
  border-radius: 10px;
  font-size: 0.8rem;
  line-height: 1.55;
  color: var(--label);
}

.user-bubble {
  background: rgba(10, 132, 255, 0.12);
  border: 1px solid rgba(10, 132, 255, 0.2);
}

.brain-bubble {
  background: var(--surface-raised);
  border: 1px solid var(--separator-soft);
}

.streaming-bubble {
  border-color: rgba(10, 132, 255, 0.3);
  background: rgba(10, 132, 255, 0.05);
  min-height: 2rem;
}

.msg-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.response-text {
  max-height: 400px;
  overflow-y: auto;
}

/* Meta */
.msg-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.25rem;
  font-size: 0.6rem;
  color: var(--tertiary);
}

.status-badge {
  font-size: 0.55rem;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-weight: 550;
}

.status-badge.active {
  background: var(--blue-soft);
  color: #64d2ff;
}

.status-badge.complete {
  background: rgba(48, 209, 88, 0.12);
  color: var(--green);
}

.status-badge.error {
  background: rgba(255, 69, 58, 0.12);
  color: var(--red);
}

/* Thinking toggle */
.thinking-toggle,
.response-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
  font-size: 0.7rem;
  color: var(--secondary);
  background: rgba(118, 118, 128, 0.08);
  margin-bottom: 0.3rem;
}

.thinking-toggle:hover,
.response-toggle:hover {
  background: rgba(118, 118, 128, 0.16);
  color: var(--label);
}

.thinking-icon {
  font-size: 0.55rem;
}

.thinking-label {
  font-weight: 600;
}

.thinking-badge {
  font-size: 0.55rem;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  background: rgba(191, 90, 242, 0.14);
  color: #da8fff;
}

.thinking-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--blue);
  animation: pulse-dot 1.5s ease-in-out infinite;
  margin-left: auto;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}

.thinking-body {
  padding: 0.5rem 0.6rem;
  background: var(--surface);
  border-radius: 8px;
  border: 1px solid var(--separator-soft);
}

.thinking-text {
  margin: 0;
  font-size: 0.7rem;
  color: var(--secondary);
  white-space: pre-wrap;
  line-height: 1.5;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
}

/* Plan summary in thinking */
.plan-summary {
  margin-top: 0.5rem;
}

.plan-summary-label {
  font-size: 0.6rem;
  color: var(--secondary);
  font-weight: 600;
  display: block;
  margin-bottom: 0.3rem;
}

.plan-task-chip {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.2rem 0.5rem;
  margin-bottom: 0.2rem;
  border-radius: 5px;
  background: var(--surface-raised);
  font-size: 0.65rem;
  color: var(--label);
}

.plan-task-agent {
  font-size: 0.55rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: var(--blue-soft);
  color: #64d2ff;
  font-weight: 600;
}

/* Streaming text */
.streaming-thinking {
  font-size: 0.75rem;
  color: var(--secondary);
  font-style: italic;
  margin-bottom: 0.3rem;
}

.streaming-response {
  font-size: 0.8rem;
  color: var(--label);
  white-space: pre-wrap;
}

.streaming-wait {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--tertiary);
  font-size: 0.8rem;
}

.wait-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--blue);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

.typing-cursor {
  display: inline-block;
  color: var(--blue);
  animation: blink-cursor 0.8s step-end infinite;
  font-weight: 300;
  margin-left: 1px;
}

@keyframes blink-cursor {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* Memory mini */
.memory-mini {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.6rem;
  border-radius: 6px;
  background: rgba(191, 90, 242, 0.06);
  border: 1px solid rgba(191, 90, 242, 0.12);
  font-size: 0.65rem;
  color: var(--secondary);
}

.memory-icon {
  font-size: 0.8rem;
}

/* Fork button on completed turns */
.fork-btn {
  margin-left: auto;
  border: 0;
  border-radius: 5px;
  padding: 0.15rem 0.4rem;
  background: rgba(191, 90, 242, 0.08);
  color: var(--tertiary);
  cursor: pointer;
  font-size: 0.55rem;
  font-weight: 550;
  transition: background 0.15s, color 0.15s;
}

.fork-btn:hover {
  background: rgba(191, 90, 242, 0.18);
  color: #da8fff;
}
</style>
