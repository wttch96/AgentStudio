<script setup lang="ts">
/**
 * TodoPanel — Kanban 式任务跟踪看板。
 * 从后端 /runs/:runId/todos 加载数据，支持状态更新。
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { api } from '../api/client'
import type { TodoItem } from '../types'

const props = defineProps<{ runId: string | null }>()

const todos = ref<TodoItem[]>([])
const error = ref('')
let timer: ReturnType<typeof setInterval> | null = null

const STATUS_LABELS: Record<string, string> = {
  pending: '待办',
  in_progress: '进行中',
  completed: '已完成',
  blocked: '阻塞',
}
const STATUS_ORDER = ['pending', 'in_progress', 'completed', 'blocked']

const columns = computed(() => {
  const map: Record<string, TodoItem[]> = { pending: [], in_progress: [], completed: [], blocked: [] }
  for (const t of todos.value) {
    map[t.status]?.push(t)
  }
  return STATUS_ORDER.map(s => ({ status: s, label: STATUS_LABELS[s], items: map[s] || [] }))
})

watch(
  () => props.runId,
  (id) => {
    if (id) {
      load(id)
      startPolling(id)
    } else {
      stopPolling()
      todos.value = []
    }
  }
)

onUnmounted(() => stopPolling())

async function load(runId: string) {
  try {
    const resp = await api.todos(runId)
    todos.value = resp.items
    error.value = ''
  } catch (e: any) {
    error.value = e?.message || '加载 Todo 失败'
  }
}

function startPolling(runId: string) {
  stopPolling()
  timer = setInterval(() => load(runId), 5000)
}

function stopPolling() {
  if (timer) { clearInterval(timer); timer = null }
}

async function setStatus(todo: TodoItem, status: string) {
  if (!props.runId || todo.status === status) return
  try {
    await api.updateTodo(props.runId, todo.id, status)
    todo.status = status as TodoItem['status']
  } catch (e: any) {
    error.value = e?.message || '更新失败'
  }
}

function progressPct(): number {
  if (!todos.value.length) return 0
  const done = todos.value.filter(t => t.status === 'completed').length
  return Math.round((done / todos.value.length) * 100)
}
</script>

<template>
  <div class="todo-panel">
    <div class="todo-header">
      <span class="todo-title">任务看板</span>
      <span v-if="todos.length" class="todo-progress">{{ progressPct() }}% ({{ todos.filter(t => t.status === 'completed').length }}/{{ todos.length }})</span>
    </div>

    <div v-if="error" class="todo-error">{{ error }}</div>

    <div v-if="!props.runId" class="todo-empty">选择运行后查看任务列表</div>

    <div class="todo-cols">
      <div v-for="col in columns" :key="col.status" class="todo-col" :class="'col-' + col.status">
        <div class="col-head">{{ col.label }} <span class="col-count">{{ col.items.length }}</span></div>
        <div class="col-body">
          <div v-for="t in col.items" :key="t.id" class="todo-card">
            <div class="card-content">{{ t.content }}</div>
            <div class="card-meta">
              <span v-if="t.assigned_to" class="card-agent">{{ t.assigned_to }}</span>
              <div class="card-actions">
                <button
                  v-for="s in STATUS_ORDER.filter(x => x !== t.status)"
                  :key="s"
                  class="card-btn"
                  :title="'设为 ' + STATUS_LABELS[s]"
                  @click="setStatus(t, s)"
                >{{ STATUS_LABELS[s] }}</button>
              </div>
            </div>
          </div>
          <div v-if="!col.items.length" class="col-empty">—</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.todo-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
}
.todo-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.todo-title { font-weight: 600; font-size: 14px; }
.todo-progress { font-size: 12px; color: var(--text-muted, #888); }
.todo-error { color: var(--danger, #e00); font-size: 12px; }
.todo-empty  { color: var(--text-muted, #888); font-size: 13px; text-align: center; padding: 24px 0; }

.todo-cols {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.todo-col {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 6px;
  background: var(--bg-secondary, #fafafa);
  min-height: 0;
}
.col-head {
  font-size: 11px;
  font-weight: 600;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-color, #ddd);
  display: flex;
  justify-content: space-between;
}
.col-count { color: var(--text-muted, #888); font-weight: 400; }
.col-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.col-empty { color: var(--text-muted, #888); font-size: 12px; text-align: center; padding: 8px; }

.todo-card {
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-light, #eee);
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 12px;
}
.card-content {
  margin-bottom: 4px;
  line-height: 1.4;
}
.card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}
.card-agent {
  font-size: 10px;
  color: var(--brand, #409eff);
  background: var(--brand-light, #ecf5ff);
  padding: 1px 6px;
  border-radius: 3px;
}
.card-actions {
  display: flex;
  gap: 2px;
}
.card-btn {
  font-size: 9px;
  padding: 1px 4px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 3px;
  background: var(--bg-secondary, #fefefe);
  cursor: pointer;
  color: var(--text-muted, #888);
}
.card-btn:hover { color: var(--brand, #409eff); border-color: var(--brand, #409eff); }

/* Status color tints */
.col-pending  { --tint: #e6a23c; }
.col-in_progress { --tint: #409eff; }
.col-completed { --tint: #67c23a; }
.col-blocked { --tint: #f56c6c; }
.todo-col .col-head { border-left: 3px solid var(--tint); }
</style>
