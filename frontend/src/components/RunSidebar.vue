<script setup lang="ts">
import type { Run } from '../types'

defineProps<{ runs: Run[]; activeId?: string }>()
const emit = defineEmits<{ select: [id: string]; create: []; delete: [id: string] }>()

function relativeTime(value: string) {
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`)
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60_000))
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`
  return `${Math.floor(minutes / 1440)} 天前`
}

function requestDelete(run: Run) {
  if (!window.confirm(`确定删除“${run.objective}”及其全部时间线记录吗？此操作无法撤销。`)) return
  emit('delete', run.id)
}
</script>

<template>
  <aside class="sidebar">
    <button class="new-run-button" type="button" @click="$emit('create')">
      <span aria-hidden="true">＋</span> 新建任务
    </button>
    <div class="sidebar-label">最近运行</div>
    <nav class="run-list" aria-label="任务历史">
      <div
        v-for="run in runs"
        :key="run.id"
        class="run-item"
        :class="{ active: run.id === activeId }"
      >
        <button type="button" class="run-select" @click="$emit('select', run.id)">
          <span class="run-status" :class="run.status" aria-hidden="true" />
          <span class="run-copy">
            <strong>{{ run.objective }}</strong>
            <small>
              <span v-if="run.turn_index > 1" class="turn-badge">续 · {{ run.turn_index }}</span>
              {{ relativeTime(run.created_at) }}
            </small>
          </span>
        </button>
        <button
          type="button"
          class="run-delete"
          :disabled="run.status === 'queued' || run.status === 'running'"
          :title="run.status === 'queued' || run.status === 'running' ? '请先停止正在执行的任务' : '删除运行记录'"
          :aria-label="`删除任务：${run.objective}`"
          @click="requestDelete(run)"
        >
          ×
        </button>
      </div>
      <div v-if="runs.length === 0" class="sidebar-empty">还没有运行记录</div>
    </nav>
    <div class="sidebar-footer">
      <span>127.0.0.1</span>
      <span>Local workspace</span>
    </div>
  </aside>
</template>
