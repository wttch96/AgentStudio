<script setup lang="ts">
import { ref } from 'vue'
import type { ToolCallGroup, ToolCall } from '../types'

defineProps<{
  toolCallGroups: ToolCallGroup[]
}>()

const expandedGroups = ref<Set<string>>(new Set())

function toggleGroup(key: string) {
  const next = new Set(expandedGroups.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedGroups.value = next
}

function expandAll() {
  expandedGroups.value = new Set(toolCallGroups?.map(g => g.key) ?? [])
}

function collapseAll() {
  expandedGroups.value = new Set()
}

function formatParams(params: Record<string, unknown>): string {
  try {
    return JSON.stringify(params, null, 2)
  } catch {
    return String(params)
  }
}

async function copyParams(call: ToolCall) {
  try {
    const text = formatParams(call.input)
    await navigator.clipboard.writeText(text)
  } catch {
    // 降级：忽略复制失败
  }
}

// 工具图标
const TOOL_ICONS: Record<string, string> = {
  Read: '📖', Write: '✏️', Edit: '✂️', Bash: '⚡', Grep: '🔍',
  Glob: '📁', WebSearch: '🌐', WebFetch: '📥', Skill: '◆',
  search_knowledge: '📚', get_knowledge: '📋', add_knowledge: '📝',
  copy_file: '📄', file_delete: '🗑', file_search: '🔎', move_file: '🚚',
  read_file: '📖', write_file: '✏️', list_directory: '📂',
}
</script>

<template>
  <div class="tool-timeline">
    <!-- 控制栏 -->
    <div v-if="toolCallGroups.length > 1" class="tool-controls">
      <button type="button" class="tool-ctrl-btn" @click="expandAll">展开全部</button>
      <button type="button" class="tool-ctrl-btn" @click="collapseAll">折叠全部</button>
    </div>

    <!-- 无工具调用 -->
    <div v-if="!toolCallGroups.length" class="tool-empty">
      <p>— 无工具调用 —</p>
    </div>

    <!-- 工具调用组列表 -->
    <div v-else class="tool-groups">
      <div
        v-for="group in toolCallGroups"
        :key="group.key"
        class="tool-group"
        :class="{ expanded: expandedGroups.has(group.key) }"
      >
        <!-- 组头 -->
        <button
          type="button"
          class="tool-group-header"
          :class="{ 'is-group': group.count > 1 }"
          @click="toggleGroup(group.key)"
        >
          <span class="tool-group-icon">{{ TOOL_ICONS[group.toolName] || '🔧' }}</span>
          <span class="tool-group-name">{{ group.toolName }}</span>
          <span v-if="group.count > 1" class="tool-group-count">× {{ group.count }}</span>
          <span class="tool-group-chevron">{{ expandedGroups.has(group.key) ? '▾' : '▸' }}</span>
        </button>

        <!-- 详细调用列表 -->
        <div v-if="expandedGroups.has(group.key)" class="tool-calls">
          <div
            v-for="(call, idx) in group.calls"
            :key="call.id"
            class="tool-call-item"
          >
            <div class="tool-call-head">
              <span class="tool-call-seq">#{{ idx + 1 }}</span>
              <span class="tool-call-time">{{ new Date(call.startedAt).toLocaleTimeString() }}</span>
              <button
                type="button"
                class="tool-copy-btn"
                title="复制参数"
                @click.stop="copyParams(call)"
              >
                📋
              </button>
            </div>
            <pre class="tool-call-params">{{ formatParams(call.input) }}</pre>
            <!-- 待后端补充: tool.completed 结果展示 -->
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tool-controls {
  display: flex;
  gap: 4px;
}

.tool-ctrl-btn {
  padding: 3px 8px;
  border: 0;
  border-radius: 5px;
  background: rgba(118, 118, 128, 0.12);
  color: var(--secondary);
  font-size: 0.5rem;
  cursor: pointer;
}

.tool-ctrl-btn:hover {
  background: rgba(118, 118, 128, 0.22);
  color: var(--label);
}

.tool-empty {
  text-align: center;
  padding: 20px 0;
}

.tool-empty p {
  font-size: 0.5625rem;
  color: var(--tertiary);
  font-style: italic;
  margin: 0;
}

.tool-groups {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tool-group {
  border-radius: 8px;
  background: rgba(44, 44, 46, 0.5);
  border: 1px solid var(--separator-soft);
  overflow: hidden;
  transition: border-color 0.15s;
}

.tool-group.expanded {
  border-color: var(--separator);
}

.tool-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  background: transparent;
  color: var(--label);
  cursor: pointer;
  font-size: 0.5625rem;
  text-align: left;
  transition: background 0.12s;
}

.tool-group-header:hover {
  background: rgba(255, 255, 255, 0.03);
}

.tool-group-header.is-group {
  font-weight: 600;
}

.tool-group-icon {
  font-size: 0.75rem;
  flex-shrink: 0;
}

.tool-group-name {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 0.5rem;
  font-weight: 600;
  flex: 1;
}

.tool-group-count {
  font-size: 0.5rem;
  padding: 1px 5px;
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.15);
  color: #64d2ff;
  font-weight: 600;
}

.tool-group-chevron {
  font-size: 0.5625rem;
  color: var(--tertiary);
  flex-shrink: 0;
}

/* 详细调用 */
.tool-calls {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 10px 10px;
  border-top: 1px solid var(--separator-soft);
}

.tool-call-item {
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.tool-call-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.tool-call-seq {
  font-size: 0.5rem;
  color: var(--tertiary);
  font-weight: 600;
}

.tool-call-time {
  font-size: 0.4375rem;
  color: var(--tertiary);
  flex: 1;
}

.tool-copy-btn {
  border: 0;
  background: none;
  cursor: pointer;
  font-size: 0.625rem;
  opacity: 0.5;
  padding: 0;
}

.tool-copy-btn:hover {
  opacity: 1;
}

.tool-call-params {
  margin: 0;
  padding: 8px;
  font: 0.4375rem / 1.5 ui-monospace, 'SFMono-Regular', Menlo, monospace;
  color: var(--secondary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 180px;
  overflow-y: auto;
}
</style>
