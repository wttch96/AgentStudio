<script setup lang="ts">
import type { Run } from '../types'

defineProps<{
  runs: Run[]
  activeRunId: string | null
  queueItems: { id: string; objective: string }[]
}>()

function statusBadge(s: string) {
  const map: Record<string, string> = { queued: '等待', running: '执行中', completed: '完成', failed: '失败', cancelled: '已取消' }
  return map[s] || s
}
function statusClass(s: string) {
  return s === 'running' ? 'running' : s === 'completed' ? 'completed' : s === 'failed' ? 'failed' : ''
}
</script>

<template>
  <div class="chat-history">
    <div class="chat-scroll">
      <div v-for="run in runs.slice().reverse()" :key="run.id" class="chat-turn" :class="{ active: run.id === activeRunId }">
        <!-- User message -->
        <div class="chat-msg user">
          <div class="msg-avatar">U</div>
          <div class="msg-bubble">
            <div class="msg-text">{{ run.objective }}</div>
            <div class="msg-meta">
              <span :class="'status-dot ' + statusClass(run.status)" />
              {{ statusBadge(run.status) }}
              <template v-if="run.status === 'completed' || run.status === 'failed'">
                · 第 {{ run.turn_index }} 轮
              </template>
            </div>
          </div>
        </div>
        <!-- Brain response -->
        <div v-if="run.final_answer" class="chat-msg brain">
          <div class="msg-avatar brain-avatar">B</div>
          <div class="msg-bubble">
            <div class="msg-text">{{ run.final_answer.slice(0, 600) }}{{ run.final_answer.length > 600 ? '…' : '' }}</div>
          </div>
        </div>
        <div v-else-if="run.status === 'running'" class="chat-msg brain">
          <div class="msg-avatar brain-avatar">B</div>
          <div class="msg-bubble thinking">主脑规划中…</div>
        </div>
      </div>

      <!-- Queue items -->
      <div v-for="q in queueItems" :key="q.id" class="chat-msg user queued">
        <div class="msg-avatar">Q</div>
        <div class="msg-bubble">
          <div class="msg-text">{{ q.objective }}</div>
          <div class="msg-meta"><span class="status-dot" /> 排队中</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-history {
  background: var(--surface);
  border: 1px solid var(--separator-soft);
  border-radius: 10px;
  max-height: 300px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}
.chat-scroll {
  max-height: 300px;
  overflow-y: auto;
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.chat-turn {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.5rem;
  border-radius: 6px;
}
.chat-turn.active { background: var(--blue-soft); }
.chat-msg {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
}
.msg-avatar {
  width: 24px; height: 24px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.7rem; font-weight: 700; flex-shrink: 0;
}
.user .msg-avatar { background: var(--blue); color: #fff; }
.brain .msg-avatar, .brain-avatar { background: var(--green); color: #fff; }
.queued .msg-avatar { background: var(--tertiary); color: var(--label); }
.msg-bubble {
  flex: 1; min-width: 0;
  padding: 0.4rem 0.6rem; border-radius: 6px;
  background: var(--surface-raised); font-size: 0.8rem;
  color: var(--label); line-height: 1.4;
}
.thinking { opacity: 0.6; font-style: italic; }
.msg-meta { font-size: 0.65rem; color: var(--tertiary); margin-top: 0.2rem; display: flex; align-items: center; gap: 0.25rem; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; background: var(--tertiary); }
.status-dot.running { background: var(--blue); }
.status-dot.completed { background: var(--green); }
.status-dot.failed { background: var(--red); }
</style>
