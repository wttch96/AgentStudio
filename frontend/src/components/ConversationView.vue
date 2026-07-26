<script setup lang="ts">
import { computed, ref } from 'vue'
import { marked } from 'marked'
import type { RunEvent } from '../types'

const props = defineProps<{
  events: RunEvent[]
  finalAnswer: string | null
}>()

// Configure marked for safe rendering
marked.setOptions({
  breaks: true,
  gfm: true,
})

function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    return marked.parse(text) as string
  } catch {
    return escapeHtml(text)
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

const collapsedMsgs = ref<Set<number>>(new Set())
const collapsedTools = ref<Set<string>>(new Set())

function toggleMsg(idx: number) {
  if (collapsedMsgs.value.has(idx)) {
    collapsedMsgs.value.delete(idx)
  } else {
    collapsedMsgs.value.add(idx)
  }
  collapsedMsgs.value = new Set(collapsedMsgs.value)
}

function toggleTool(key: string) {
  if (collapsedTools.value.has(key)) {
    collapsedTools.value.delete(key)
  } else {
    collapsedTools.value.add(key)
  }
  collapsedTools.value = new Set(collapsedTools.value)
}

interface TimelineItem {
  timestamp: string
  type: string
  agentId: string | null
  taskId: string | null
  payload: Record<string, unknown>
  sequence: number
}

const items = computed<TimelineItem[]>(() => {
  return props.events
    .filter((e) => {
      // Include all meaningful events
      return [
        'run.started', 'run.completed', 'run.failed', 'run.cancelled',
        'plan.created', 'planner.started', 'planner.bypassed',
        'brain.contract_created', 'brain.synthesizing',
        'workspace.discovery_started',
        'wave.started', 'wave.completed',
        'agent.started', 'agent.message', 'tool.started',
        'skill.loaded', 'agent.completed', 'agent.failed',
        'agent.usage', 'run.summary',
        'interrupt.requested', 'interrupt.received', 'interrupt.resolved',
        'flow.started', 'flow.completed',
      ].includes(e.type)
    })
    .map((e) => ({
      timestamp: e.timestamp,
      type: e.type,
      agentId: e.agent_id,
      taskId: e.task_id,
      payload: e.payload,
      sequence: e.sequence,
    }))
})

function formatTime(ts: string): string {
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function typeLabel(type: string): string {
  const labels: Record<string, string> = {
    'run.started': '运行开始',
    'run.completed': '运行完成',
    'run.failed': '运行失败',
    'run.cancelled': '运行已取消',
    'plan.created': 'DAG 计划生成',
    'planner.started': '主脑规划',
    'planner.bypassed': '跳过规划',
    'brain.contract_created': '共享契约',
    'brain.synthesizing': '主脑汇总',
    'workspace.discovery_started': '工作空间发现',
    'wave.started': '调度波次开始',
    'wave.completed': '调度波次完成',
    'agent.started': 'Agent 启动',
    'agent.message': '消息',
    'tool.started': '工具调用',
    'skill.loaded': '加载 Skill',
    'agent.completed': '完成',
    'agent.failed': '失败',
    'agent.usage': '用量统计',
    'run.summary': '最终汇总',
    'interrupt.requested': '中断请求',
    'interrupt.received': '中断接收',
    'interrupt.resolved': '中断已处理',
    'flow.started': '流程开始',
    'flow.completed': '流程完成',
  }
  return labels[type] || type
}

function typeIcon(type: string): string {
  if (type.startsWith('run.')) return '&#x25C9;'
  if (type.startsWith('plan.') || type.startsWith('planner.')) return '&#x25A3;'
  if (type.startsWith('wave.')) return '&#x2263;'
  if (type.startsWith('agent.message')) return '&#x25AC;'
  if (type.startsWith('tool.')) return '&#x2699;'
  if (type.startsWith('skill.')) return '&#x25C6;'
  if (type.startsWith('agent.')) return '&#x25CF;'
  if (type.startsWith('brain.')) return '&#x25A0;'
  if (type.startsWith('interrupt.')) return '&#x26A0;'
  if (type.startsWith('flow.')) return '&#x2691;'
  return '&#x25CB;'
}

function typeCssClass(type: string): string {
  if (type.startsWith('run.')) return 'event-run'
  if (type.startsWith('plan.') || type.startsWith('planner.')) return 'event-plan'
  if (type.startsWith('wave.')) return 'event-wave'
  if (type.startsWith('agent.message')) return 'event-message'
  if (type.startsWith('tool.') || type.startsWith('skill.')) return 'event-tool'
  if (type.startsWith('agent.completed')) return 'event-success'
  if (type.startsWith('agent.failed')) return 'event-error'
  if (type.startsWith('brain.')) return 'event-brain'
  if (type.startsWith('interrupt.')) return 'event-interrupt'
  if (type.startsWith('flow.')) return 'event-flow'
  if (type.startsWith('agent.')) return 'event-agent'
  return 'event-default'
}

function isMessage(item: TimelineItem): boolean {
  return item.type === 'agent.message'
}

function isTool(item: TimelineItem): boolean {
  return item.type === 'tool.started' || item.type === 'skill.loaded'
}

function toolKey(item: TimelineItem): string {
  return `${item.sequence}`
}
</script>

<template>
  <section v-if="items.length || finalAnswer" class="conversation-view">
    <div class="conv-header">
      <span class="eyebrow">对话记录</span>
      <span>{{ items.length }} 条事件</span>
    </div>

    <div class="conv-list">
      <article
        v-for="(item, idx) in items"
        :key="item.sequence"
        :class="['conv-item', typeCssClass(item.type)]"
      >
        <!-- Header bar -->
        <div class="conv-item-header" @click="toggleMsg(idx)">
          <span class="conv-time">{{ formatTime(item.timestamp) }}</span>
          <span class="conv-icon" v-html="typeIcon(item.type)" />
          <span class="conv-type">{{ typeLabel(item.type) }}</span>
          <span v-if="item.agentId" class="conv-agent">{{ item.agentId }}</span>
          <span v-if="item.taskId" class="conv-task">{{ item.taskId }}</span>
          <ElButton text circle class="conv-toggle" :class="{ open: !collapsedMsgs.has(idx) }">
            {{ collapsedMsgs.has(idx) ? '&#x25B6;' : '&#x25BC;' }}
          </ElButton>
        </div>

        <!-- Content body -->
        <div v-if="!collapsedMsgs.has(idx)" class="conv-item-body">
          <!-- Agent message with Markdown -->
          <div
            v-if="isMessage(item) && typeof item.payload.text === 'string'"
            class="conv-markdown"
            v-html="renderMarkdown(item.payload.text)"
          />

          <!-- Tool call -->
          <div
            v-else-if="isTool(item)"
            class="conv-tool"
          >
            <div class="conv-tool-header" @click="toggleTool(toolKey(item))">
              <span>{{ item.type === 'skill.loaded' ? 'Skill: ' : 'Tool: ' }}</span>
              <code>{{ item.type === 'skill.loaded' ? item.payload.skill : item.payload.tool }}</code>
              <ElButton text circle size="small" class="conv-toggle small">
                {{ collapsedTools.has(toolKey(item)) ? '&#x25B6;' : '&#x25BC;' }}
              </ElButton>
            </div>
            <pre
              v-if="!collapsedTools.has(toolKey(item))"
              class="conv-tool-input"
            >{{ JSON.stringify(item.payload.input || item.payload, null, 2) }}</pre>
          </div>

          <!-- Other events -->
          <pre v-else class="conv-payload">{{ JSON.stringify(item.payload, null, 2) }}</pre>
        </div>
      </article>
    </div>

    <!-- Final answer -->
    <article v-if="finalAnswer" class="conv-final">
      <div class="conv-final-header">
        <span class="conv-icon">&#x2726;</span>
        <span>最终汇总</span>
      </div>
      <div class="conv-markdown" v-html="renderMarkdown(finalAnswer)" />
    </article>
  </section>
  <section v-else class="conv-empty">
    <p>暂无对话记录。提交任务后这里将展示 Agent 与主脑的完整交互。</p>
  </section>
</template>

<style scoped>
.conversation-view {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.conv-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.conv-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.conv-item {
  border-left: 3px solid transparent;
  background: var(--bg-primary, #fff);
  border-radius: 4px;
  overflow: hidden;
}

.conv-item-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.6rem;
  cursor: pointer;
  user-select: none;
  font-size: var(--ui-font-sm);
  background: var(--bg-secondary, #f8fafc);
}

.conv-item-header:hover {
  background: var(--bg-hover, #f1f5f9);
}

.conv-time {
  font-family: monospace;
  color: var(--text-secondary, #64748b);
  font-size: var(--ui-font-sm);
  min-width: 70px;
}

.conv-icon { font-size: var(--ui-font-xs); }
.conv-type { font-weight: 600; }
.conv-agent {
  font-size: var(--ui-font-xs);
  background: var(--bg-tertiary, #e2e8f0);
  padding: 0 0.35rem;
  border-radius: 3px;
}
.conv-task {
  font-size: var(--ui-font-xs);
  color: var(--text-secondary);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-toggle {
  margin-left: auto;
  background: none;
  border: none;
  cursor: pointer;
  font-size: var(--ui-font-xs);
  color: var(--text-secondary);
  padding: 0;
}
.conv-toggle.small { font-size: var(--ui-font-xs); }

.conv-item-body {
  padding: 0.5rem 0.75rem;
}

/* Color-coded left border */
.event-run { border-left-color: #6366f1; }
.event-plan { border-left-color: #8b5cf6; }
.event-wave { border-left-color: #06b6d4; }
.event-message { border-left-color: #3b82f6; }
.event-tool { border-left-color: #f59e0b; }
.event-success { border-left-color: #22c55e; }
.event-error { border-left-color: #ef4444; }
.event-brain { border-left-color: #ec4899; }
.event-agent { border-left-color: #64748b; }
.event-interrupt { border-left-color: #f97316; }
.event-default { border-left-color: #cbd5e1; }

/* Markdown content */
.conv-markdown {
  font-size: var(--ui-font-base);
  line-height: 1.6;
  color: var(--text-primary, #1e293b);
}

.conv-markdown :deep(h1), .conv-markdown :deep(h2), .conv-markdown :deep(h3) {
  font-size: var(--ui-font-lg);
  margin: 0.5rem 0 0.25rem;
  font-weight: 600;
}

.conv-markdown :deep(p) { margin: 0.3rem 0; }

.conv-markdown :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 0.6rem 0.8rem;
  border-radius: 6px;
  overflow-x: auto;
  font-size: var(--ui-font-sm);
  line-height: 1.45;
  margin: 0.4rem 0;
}

.conv-markdown :deep(code) {
  background: var(--bg-secondary, #f1f5f9);
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  font-size: var(--ui-font-sm);
}

.conv-markdown :deep(pre code) {
  background: none;
  padding: 0;
}

.conv-markdown :deep(ul), .conv-markdown :deep(ol) {
  padding-left: 1.5rem;
  margin: 0.3rem 0;
}

.conv-markdown :deep(blockquote) {
  border-left: 3px solid #e2e8f0;
  padding-left: 0.75rem;
  margin: 0.3rem 0;
  color: var(--text-secondary);
}

.conv-markdown :deep(table) {
  border-collapse: collapse;
  font-size: var(--ui-font-sm);
}

.conv-markdown :deep(th), .conv-markdown :deep(td) {
  border: 1px solid #e2e8f0;
  padding: 0.25rem 0.5rem;
  text-align: left;
}

.conv-markdown :deep(th) {
  background: var(--bg-secondary, #f8fafc);
}

/* Tool call */
.conv-tool-header {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  cursor: pointer;
  font-size: var(--ui-font-sm);
  color: var(--text-secondary);
}

.conv-tool-header code {
  font-size: var(--ui-font-sm);
  background: #fef3c7;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  color: #92400e;
}

.conv-tool-input {
  margin-top: 0.35rem;
  font-size: var(--ui-font-sm);
  background: var(--bg-secondary, #f8fafc);
  padding: 0.4rem 0.6rem;
  border-radius: 4px;
  overflow-x: auto;
  max-height: 180px;
  overflow-y: auto;
}

.conv-payload {
  font-size: var(--ui-font-sm);
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}

/* Final answer */
.conv-final {
  margin-top: 0.75rem;
  border: 2px solid #22c55e;
  border-radius: 8px;
  overflow: hidden;
}

.conv-final-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: #f0fdf4;
  font-weight: 600;
  font-size: var(--ui-font-md);
}

.conv-final .conv-markdown {
  padding: 0.75rem;
}

.conv-empty {
  text-align: center;
  padding: 2rem 1rem;
  color: var(--text-secondary);
}
</style>
