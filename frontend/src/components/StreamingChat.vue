<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { ConversationTurn, PlanTask, RunEvent, StreamingState } from '../types'

const props = defineProps<{
  turns: ConversationTurn[]
  events: RunEvent[]
  streaming: StreamingState
  activeRunId: string | null
  isRunning: boolean
}>()

const emit = defineEmits<{
  interrupt: []
  fork: [runId: string]
  showDag: []
}>()

const chatScroll = ref<HTMLElement | null>(null)
const thinkingCollapsed = ref<Set<string>>(new Set())
const responseCollapsed = ref<Set<string>>(new Set())
const taskDetailCollapsed = ref<Set<string>>(new Set())

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

function toggleTaskDetail(turnId: string) {
  const next = new Set(taskDetailCollapsed.value)
  if (next.has(turnId)) next.delete(turnId)
  else next.add(turnId)
  taskDetailCollapsed.value = next
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

// Task status helpers
const agentEventTypes = new Set([
  'agent.started', 'agent.message', 'tool.started', 'skill.loaded',
  'agent.completed', 'agent.failed',
])

function taskStatusForTurn(turn: ConversationTurn, taskId: string): 'pending' | 'running' | 'completed' | 'failed' {
  const evs = props.events.filter(e => e.run_id === turn.runId && e.task_id === taskId && agentEventTypes.has(e.type))
  if (evs.some(e => e.type === 'agent.failed')) return 'failed'
  if (evs.some(e => e.type === 'agent.completed')) return 'completed'
  if (evs.some(e => e.type === 'agent.started')) return 'running'
  return 'pending'
}

function taskTimingForTurn(turn: ConversationTurn, taskId: string): string {
  const evs = props.events.filter(e => e.run_id === turn.runId && e.task_id === taskId && agentEventTypes.has(e.type))
  const started = evs.find(e => e.type === 'agent.started')
  if (!started) return ''
  const completed = evs.find(e => e.type === 'agent.completed')
  if (completed) {
    const dur = (new Date(completed.timestamp).getTime() - new Date(started.timestamp).getTime()) / 1000
    return `${dur.toFixed(1)}s`
  }
  const failed = evs.find(e => e.type === 'agent.failed')
  if (failed) {
    const dur = (new Date(failed.timestamp).getTime() - new Date(started.timestamp).getTime()) / 1000
    return `${dur.toFixed(1)}s`
  }
  const elapsed = Math.floor((Date.now() - new Date(started.timestamp).getTime()) / 1000)
  return `${elapsed}s`
}

function taskFailureReason(turn: ConversationTurn, taskId: string): string {
  const evs = props.events.filter(e => e.run_id === turn.runId && e.task_id === taskId)
  const failure = evs.find(e => e.type === 'agent.failed')
  if (!failure) return ''
  return (failure.payload.error as string) || (failure.payload.summary as string) || '未知错误'
}

// Group tasks by wave (dependency level) for vertical swimlane layout
function groupTasksByWave(tasks: PlanTask[]): PlanTask[][] {
  const byId = new Map(tasks.map(t => [t.id, t]))
  const levels = new Map<string, number>()

  function getLevel(task: PlanTask): number {
    if (levels.has(task.id)) return levels.get(task.id)!
    const deps = task.depends_on.map(id => byId.get(id)).filter(Boolean) as PlanTask[]
    const lvl = deps.length ? Math.max(...deps.map(getLevel)) + 1 : 0
    levels.set(task.id, lvl)
    return lvl
  }

  tasks.forEach(getLevel)
  const groups = new Map<number, PlanTask[]>()
  tasks.forEach(t => {
    const lvl = levels.get(t.id)!
    if (!groups.has(lvl)) groups.set(lvl, [])
    groups.get(lvl)!.push(t)
  })
  return [...groups.entries()].sort(([a], [b]) => a - b).map(([, ts]) => ts)
}

const statusDot: Record<string, string> = {
  pending: '○',
  running: '◉',
  completed: '✓',
  failed: '✕',
}

const displayTurns = computed(() => {
  return props.turns
})

// Auto-scroll to bottom
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
        <div class="chat-empty-icon">💬</div>
        <h3>开始对话</h3>
        <p>在下方输入目标，主脑将调度 Agent 团队执行。</p>
      </div>

      <!-- Conversation turns -->
      <template v-for="turn in displayTurns" :key="turn.id">
        <div class="chat-turn" :class="{ active: turn.runId === activeRunId }">
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

          <!-- Thinking + Task flow inline -->
          <div v-if="turn.thinkingText || turn.planTasks.length" class="chat-msg brain">
            <div class="msg-avatar brain-avatar" aria-hidden="true">B</div>
            <div class="msg-content">
              <div
                class="thinking-toggle"
                @click="toggleThinking(turn.id)"
                role="button"
                :aria-expanded="!thinkingCollapsed.has(turn.id)"
              >
                <span class="thinking-icon">{{ thinkingCollapsed.has(turn.id) ? '▶' : '▼' }}</span>
                <span class="thinking-label">主脑规划过程</span>
                <span v-if="turn.planTasks.length" class="thinking-badge">
                  {{ turn.planTasks.length }} 个任务
                </span>
                <span v-if="turn.status === 'thinking' && turn.runId === activeRunId" class="thinking-pulse" />
              </div>

              <!-- Thinking body with inline task flow -->
              <div v-if="!thinkingCollapsed.has(turn.id)" class="thinking-body">
                <div v-if="turn.thinkingText" class="thinking-output">
                  <div class="thinking-output-label">主脑输出</div>
                  <pre class="thinking-text">{{ turn.thinkingText }}</pre>
                </div>

                <!-- Task flow inline nodes — vertical swimlanes grouped by wave -->
                <div v-if="turn.planTasks.length" class="task-flow-inline">
                  <div class="task-flow-label">
                    <span>⚙ 任务流程节点</span>
                    <button
                      type="button"
                      class="dag-link-btn"
                      @click.stop="emit('showDag')"
                      title="查看完整DAG图"
                    >◇ 展开完整DAG</button>
                  </div>

                  <div class="task-swimlanes">
                    <div
                      v-for="(wave, wi) in groupTasksByWave(turn.planTasks.filter(t => !t.agent?.includes('brain')))"
                      :key="'w' + wi"
                      class="task-wave"
                    >
                      <div class="wave-label">
                        <span class="wave-icon">{{ wave.length > 1 ? '⑂' : '→' }}</span>
                        {{ wave.length > 1 ? `Wave ${wi + 1} · ${wave.length} 节点并行` : '' }}
                      </div>
                      <div class="task-list">
                        <div
                          v-for="task in wave"
                          :key="task.id"
                          class="task-node-inline"
                          :class="taskStatusForTurn(turn, task.id)"
                        >
                          <div class="task-node-header">
                            <span class="task-node-dot" :class="taskStatusForTurn(turn, task.id)">
                              {{ statusDot[taskStatusForTurn(turn, task.id)] }}
                            </span>
                            <span class="task-node-agent">{{ task.agent }}</span>
                            <span class="task-node-title">{{ task.title }}</span>
                            <span v-if="taskTimingForTurn(turn, task.id)" class="task-node-time">
                              {{ taskTimingForTurn(turn, task.id) }}
                            </span>
                          </div>
                          <!-- Expandable detail -->
                          <div v-if="!taskDetailCollapsed.has(`${turn.id}-${task.id}`)" class="task-node-detail">
                            <div class="task-detail-row">
                              <span class="task-detail-label">目标：</span>
                              <span class="task-detail-value">{{ task.objective.slice(0, 150) }}{{ task.objective.length > 150 ? '…' : '' }}</span>
                            </div>
                            <div v-if="task.depends_on.length" class="task-detail-row">
                              <span class="task-detail-label">依赖：</span>
                              <span class="task-detail-value">{{ task.depends_on.join(', ') }}</span>
                            </div>
                            <div v-if="task.write_scope.length" class="task-detail-row">
                              <span class="task-detail-label">写范围：</span>
                              <span class="task-detail-value">{{ task.write_scope.join(', ') }}</span>
                            </div>
                          </div>
                          <!-- Failure detail -->
                          <div
                            v-if="taskStatusForTurn(turn, task.id) === 'failed'"
                            class="task-failure-detail"
                          >
                            <span class="task-failure-label">失败原因：</span>
                            <pre class="task-failure-text">{{ taskFailureReason(turn, task.id) }}</pre>
                          </div>
                          <button
                            type="button"
                            class="task-expand-btn"
                            @click.stop="toggleTaskDetail(`${turn.id}-${task.id}`)"
                          >
                            {{ taskDetailCollapsed.has(`${turn.id}-${task.id}`) ? '展开详情' : '收起详情' }}
                          </button>
                        </div>
                      </div>
                    </div>
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
                <span class="thinking-icon">{{ responseCollapsed.has(turn.id) ? '▶' : '▼' }}</span>
                <span class="thinking-label">主脑响应</span>
              </div>
              <div v-if="!responseCollapsed.has(turn.id) && turn.brainResponse" class="msg-bubble brain-bubble">
                <div class="msg-text response-text">{{ turn.brainResponse }}</div>
              </div>
              <!-- Streaming indicator -->
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

          <!-- Memory compaction -->
          <div v-if="turn.memoryEvents.length" class="chat-msg system">
            <div class="msg-avatar sys-avatar" aria-hidden="true">M</div>
            <div class="msg-content">
              <div class="memory-mini">
                <span class="memory-icon">🧠</span>
                <span>
                  {{ turn.memoryEvents.length }} 次记忆压缩 ·
                  最后压缩: Wave {{ turn.memoryEvents[turn.memoryEvents.length - 1].wave }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Active streaming: no turn yet -->
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
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: var(--content-width);
  margin: 0 auto;
  padding-bottom: 175px;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.chat-scroll {
  flex: 1 1 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 1rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-height: 0;
  word-break: break-word;
  overflow-wrap: break-word;
  -webkit-overflow-scrolling: touch;
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
  min-width: 0;
  overflow: hidden;
  flex-shrink: 0;
}

.chat-turn.active {
  border-radius: 10px;
  background: rgba(10, 132, 255, 0.05);
  border: 1px solid rgba(10, 132, 255, 0.1);
}
.chat-turn.active .chat-msg {
  padding: 0 0.5rem;
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
  overflow: hidden;
}

.msg-bubble {
  padding: 0.6rem 0.85rem;
  border-radius: 10px;
  font-size: 0.8rem;
  line-height: 1.55;
  color: var(--label);
  overflow-x: auto;
  max-width: 100%;
  word-break: break-word;
  overflow-wrap: break-word;
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
  overflow-wrap: break-word;
  max-width: 100%;
  overflow-x: auto;
}

.response-text {
  max-height: 400px;
  overflow-y: auto;
  overflow-x: hidden;
  word-break: break-word;
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
  animation: dot-pulse 1s ease-in-out infinite;
  margin-left: auto;
}

@keyframes dot-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.3; transform: scale(1.3); }
}
.thinking-body {
  padding: 0.5rem 0.6rem;
  background: var(--surface);
  border-radius: 8px;
  border: 1px solid var(--separator-soft);
  overflow: hidden;
}

.thinking-text {
  margin: 0;
  font-size: 0.7rem;
  color: var(--secondary);
  white-space: pre-wrap;
  line-height: 1.5;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
}

/* Task flow inline */
.task-flow-inline {
  margin-top: 0.6rem;
}

.task-flow-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.4rem;
  font-size: 0.65rem;
  color: var(--secondary);
  font-weight: 600;
}

.dag-link-btn {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 3px 10px;
  border: 1px solid rgba(10, 132, 255, 0.25);
  border-radius: 6px;
  background: rgba(10, 132, 255, 0.08);
  color: #64d2ff;
  font-size: 0.6rem;
  font-weight: 550;
  cursor: pointer;
  transition: background 0.15s;
}

.dag-link-btn:hover {
  background: rgba(10, 132, 255, 0.16);
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.task-node-inline {
  padding: 0.4rem 0.55rem;
  border-radius: 8px;
  border: 1px solid var(--separator-soft);
  background: var(--surface-raised);
  transition: border-color 0.15s;
}

.task-node-inline.running {
  border-color: rgba(10, 132, 255, 0.25);
  animation: task-pulse 2s ease-in-out infinite;
}

@keyframes task-pulse {
  0%, 100% { border-color: rgba(10, 132, 255, 0.1); opacity: 1; }
  50% { border-color: rgba(10, 132, 255, 0.45); opacity: 0.75; }
}

.task-node-inline.completed {
  border-color: rgba(48, 209, 88, 0.2);
}

.task-node-inline.failed {
  border-color: rgba(255, 69, 58, 0.3);
  background: rgba(255, 69, 58, 0.04);
}

.task-node-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.task-node-dot {
  font-size: 0.55rem;
  flex-shrink: 0;
}

.task-node-dot.pending { color: var(--tertiary); }
.task-node-dot.running { color: var(--blue); animation: dot-pulse 1s ease-in-out infinite; }
.task-node-dot.completed { color: var(--green); }
.task-node-dot.failed { color: var(--red); }

.task-node-agent {
  font-size: 0.55rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: var(--blue-soft);
  color: #64d2ff;
  font-weight: 600;
  flex-shrink: 0;
}

.task-node-title {
  font-size: 0.65rem;
  color: var(--label);
  font-weight: 550;
}

.task-node-time {
  margin-left: auto;
  font-size: 0.5rem;
  color: var(--tertiary);
  font-variant-numeric: tabular-nums;
}

.task-expand-btn {
  margin-top: 0.35rem;
  border: 0;
  background: none;
  color: var(--tertiary);
  cursor: pointer;
  font-size: 0.5rem;
  padding: 1px 0;
}

.task-expand-btn:hover {
  color: var(--secondary);
}

.task-node-detail {
  margin-top: 0.35rem;
  padding: 0.35rem 0.5rem;
  background: rgba(0, 0, 0, 0.12);
  border-radius: 6px;
}

.task-detail-row {
  display: flex;
  gap: 0.3rem;
  margin-bottom: 0.2rem;
  font-size: 0.55rem;
  line-height: 1.4;
}

.task-detail-row:last-child {
  margin-bottom: 0;
}

.task-detail-label {
  flex-shrink: 0;
  color: var(--tertiary);
  font-weight: 600;
}

.task-detail-value {
  color: var(--secondary);
  word-break: break-word;
}

/* Task failure detail */
.task-failure-detail {
  margin-top: 0.3rem;
  padding: 0.35rem 0.5rem;
  background: rgba(255, 69, 58, 0.1);
  border: 1px solid rgba(255, 69, 58, 0.2);
  border-radius: 6px;
}

.task-failure-label {
  font-size: 0.5rem;
  font-weight: 600;
  color: #ff6961;
}

.task-failure-text {
  margin: 0.2rem 0 0;
  font-size: 0.5rem;
  color: var(--secondary);
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
  max-height: 120px;
  overflow-y: auto;
}

/* Wave grouping in swimlanes */
.task-swimlanes {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.task-wave {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.wave-label {
  font-size: 0.55rem;
  color: var(--tertiary);
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  background: rgba(118, 118, 128, 0.08);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.wave-icon {
  font-size: 0.7rem;
  color: var(--blue);
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

/* Fork button */
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

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}
</style>
