<script setup lang="ts">
/**
 * TodoPanel — Kanban 式任务跟踪看板。
 * 从后端 /runs/:runId/todos 加载数据，支持状态更新。
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { api } from '../api/client'
import type { BlackboardEntry, PlanTask, RunEvent, TodoItem } from '../types'

const props = defineProps<{
  runId: string | null
  tasks: PlanTask[]
  events: RunEvent[]
}>()

const todos = ref<TodoItem[]>([])
const taskRecords = ref<Record<string, BlackboardEntry[]>>({})
const sharedRecords = ref<BlackboardEntry[]>([])
const error = ref('')
let timer: ReturnType<typeof setInterval> | null = null

const STATUS_LABELS: Record<string, string> = {
  pending: '待办',
  backlog: '待办',
  ready: '待办',
  in_progress: '进行中',
  review: '审查',
  completed: '已完成',
  failed: '阻塞',
  cancelled: '阻塞',
  blocked: '阻塞',
}
const STATUS_ORDER = ['pending', 'in_progress', 'review', 'completed', 'blocked']
const COLUMN_META: Record<string, { icon: string; hint: string }> = {
  pending: { icon: '○', hint: '等待开始' },
  in_progress: { icon: '◉', hint: '正在处理' },
  review: { icon: '◇', hint: '等待验收' },
  completed: { icon: '✓', hint: '已经完成' },
  blocked: { icon: '!', hint: '需要处理' },
}

function normalizeStatus(status: string) {
  if (['backlog', 'ready'].includes(status)) return 'pending'
  if (['failed', 'cancelled'].includes(status)) return 'blocked'
  return status
}

function eventStatus(taskId: string): TodoItem['status'] | null {
  const taskEvents = props.events.filter(event => (
    event.run_id === props.runId && event.task_id === taskId
  ))
  if (taskEvents.some(event => event.type === 'agent.failed')) return 'failed'
  if (taskEvents.some(event => event.type === 'agent.completed')) return 'completed'
  if (taskEvents.some(event => event.type === 'agent.started')) return 'in_progress'
  return null
}

const displayTodos = computed<TodoItem[]>(() => {
  const stored = new Map(todos.value.map(todo => [todo.id, todo]))
  const planned = props.tasks.map((task): TodoItem => {
    const existing = stored.get(task.id)
    if (existing) {
      return { ...existing, status: eventStatus(task.id) || existing.status }
    }
    return {
      id: task.id,
      title: task.title,
      content: task.title,
      objective: task.objective,
      assigned_to: task.agent || null,
      status: eventStatus(task.id) || task.status || 'pending',
      depends_on: task.depends_on || [],
      expected_outputs: task.expected_outputs || [],
      acceptance_criteria: task.acceptance_criteria || [],
      artifacts: [],
      decisions: [],
      blockers: [],
      risks: [],
      verification: {},
      created_at: '',
      updated_at: '',
      completed_at: null,
    }
  })
  const plannedIds = new Set(props.tasks.map(task => task.id))
  return [...planned, ...todos.value.filter(todo => !plannedIds.has(todo.id))]
})

const columns = computed(() => {
  const map: Record<string, TodoItem[]> = {
    pending: [], in_progress: [], review: [], completed: [], blocked: [],
  }
  for (const t of displayTodos.value) {
    const normalized = normalizeStatus(t.status)
    map[normalized]?.push(t)
  }
  return STATUS_ORDER.map(s => ({
    status: s,
    label: STATUS_LABELS[s],
    items: map[s] || [],
    ...COLUMN_META[s],
  }))
})

const completedCount = computed(
  () => displayTodos.value.filter(todo => normalizeStatus(todo.status) === 'completed').length,
)
const progressPercent = computed(
  () => displayTodos.value.length
    ? Math.round((completedCount.value / displayTodos.value.length) * 100)
    : 0,
)

watch(
  () => props.runId,
  (id) => {
    if (id) {
      load(id)
      startPolling(id)
    } else {
      stopPolling()
      todos.value = []
      taskRecords.value = {}
      sharedRecords.value = []
    }
  },
  { immediate: true },
)

onUnmounted(() => stopPolling())

async function load(runId: string) {
  try {
    const [todoResponse, blackboard] = await Promise.all([
      api.todos(runId),
      api.blackboard(runId),
    ])
    todos.value = todoResponse.items
    const grouped: Record<string, BlackboardEntry[]> = {}
    const shared: BlackboardEntry[] = []
    const derivedKeys = new Set(['__todos__', 'all_results', 'all_reviews', 'review_decisions'])
    for (const entry of Object.values(blackboard.entries)) {
      const match = entry.key.match(/^(artifact|decision|blocker|risk|log):([^:]+):|^(result|review):([^:]+)$/)
      if (match) {
        const taskId = match[2] || match[4]
        grouped[taskId] = [...(grouped[taskId] || []), entry]
      } else if (!derivedKeys.has(entry.key)) {
        shared.push(entry)
      }
    }
    taskRecords.value = grouped
    sharedRecords.value = shared.sort(
      (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
    )
    error.value = ''
  } catch (e: any) {
    error.value = e?.message || '加载 Todo 失败'
  }
}

function recordKind(entry: BlackboardEntry) {
  const kind = entry.key.split(':', 1)[0]
  return {
    artifact: '产物',
    decision: '决策',
    blocker: '阻塞',
    risk: '风险',
    log: '记录',
    result: '结果',
    review: '审查',
  }[kind] || kind
}

function recordText(entry: BlackboardEntry) {
  const value = entry.value
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object') return String(value ?? '—')
  const item = value as Record<string, unknown>
  const preferred = item.description ?? item.summary ?? item.title ?? item.path ?? item.content
  return typeof preferred === 'string' ? preferred : JSON.stringify(value)
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

function setStatusCommand(todo: TodoItem, status: unknown) {
  void setStatus(todo, String(status))
}

function availableStatuses(todo: TodoItem) {
  const current = normalizeStatus(todo.status)
  return STATUS_ORDER.filter(status => status !== current)
}

function agentInitials(agent: string) {
  return agent
    .split(/[-_\s]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0]?.toUpperCase())
    .join('')
}
</script>

<template>
  <div class="todo-panel">
    <div class="todo-header">
      <div>
        <div class="todo-title">任务看板</div>
        <div class="todo-subtitle">{{ displayTodos.length }} 个任务 · 按状态推进工作</div>
      </div>
      <div v-if="displayTodos.length" class="todo-progress">
        <span>{{ completedCount }}/{{ displayTodos.length }} 已完成</span>
        <ElProgress :percentage="progressPercent" :stroke-width="6" :show-text="false" />
        <strong>{{ progressPercent }}%</strong>
      </div>
    </div>

    <ElAlert v-if="error" type="error" :title="error" :closable="false" show-icon />

    <div v-if="!props.runId" class="todo-empty">选择运行后查看任务列表</div>

    <ElCollapse v-if="sharedRecords.length" class="shared-data">
      <ElCollapseItem name="shared">
        <template #title>运行共享数据 · {{ sharedRecords.length }}</template>
        <div class="shared-record-list">
          <div v-for="record in sharedRecords" :key="record.key" class="shared-record">
            <code>{{ record.key }}</code>
            <span>{{ recordText(record) }}</span>
          </div>
        </div>
      </ElCollapseItem>
    </ElCollapse>

    <div class="todo-cols">
      <div v-for="col in columns" :key="col.status" class="todo-col" :class="'col-' + col.status">
        <div class="col-head">
          <div class="col-title">
            <span class="col-status-icon">{{ col.icon }}</span>
            <span>{{ col.label }}</span>
            <ElTag size="small" effect="plain" round class="col-count">{{ col.items.length }}</ElTag>
          </div>
          <span class="col-hint">{{ col.hint }}</span>
        </div>
        <div class="col-body">
          <div v-for="t in col.items" :key="t.id" class="todo-card">
            <div class="card-top">
              <div class="card-content">{{ t.content }}</div>
              <ElDropdown trigger="click" @command="setStatusCommand(t, $event)">
                <ElButton text circle size="small" class="card-menu" title="变更状态">•••</ElButton>
                <template #dropdown>
                  <ElDropdownMenu>
                    <ElDropdownItem
                      v-for="s in availableStatuses(t)"
                      :key="s"
                      :command="s"
                    >
                      移至「{{ STATUS_LABELS[s] }}」
                    </ElDropdownItem>
                  </ElDropdownMenu>
                </template>
              </ElDropdown>
            </div>
            <div
              v-if="t.objective && t.objective !== t.content"
              class="card-objective"
            >{{ t.objective }}</div>

            <div
              v-if="t.acceptance_criteria?.length || t.artifacts?.length || t.blockers?.length"
              class="card-labels"
            >
              <ElTag v-if="t.acceptance_criteria?.length" size="small" effect="plain">
                验收 {{ t.acceptance_criteria.length }}
              </ElTag>
              <ElTag v-if="t.artifacts?.length" size="small" type="success" effect="plain">
                产物 {{ t.artifacts.length }}
              </ElTag>
              <ElTag v-if="t.blockers?.length" size="small" type="danger" effect="plain">
                阻塞 {{ t.blockers.length }}
              </ElTag>
            </div>

            <ElCollapse v-if="taskRecords[t.id]?.length" class="card-records">
              <ElCollapseItem :name="t.id">
                <template #title>
                  <span class="records-title">节点数据</span>
                  <span class="records-count">{{ taskRecords[t.id].length }}</span>
                </template>
                <div class="card-record-list">
                  <div v-for="record in taskRecords[t.id]" :key="record.key" class="card-record">
                    <ElTag size="small" effect="plain" class="record-kind">{{ recordKind(record) }}</ElTag>
                    <span class="record-text">{{ recordText(record) }}</span>
                  </div>
                </div>
              </ElCollapseItem>
            </ElCollapse>
            <div class="card-meta">
              <div v-if="t.assigned_to" class="card-agent">
                <ElAvatar :size="24">{{ agentInitials(t.assigned_to) }}</ElAvatar>
                <span>{{ t.assigned_to }}</span>
              </div>
              <span class="card-id">#{{ t.id.slice(0, 10) }}</span>
            </div>
          </div>
          <div v-if="!col.items.length" class="col-empty">
            <span class="empty-icon">{{ col.icon }}</span>
            <span>暂无任务</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.todo-panel {
  display: flex;
  min-height: 0;
  height: 100%;
  flex-direction: column;
  gap: 12px;
  padding: 14px 12px 12px;
  background:
    radial-gradient(circle at 12% 0%, rgba(64, 158, 255, .07), transparent 28%),
    var(--el-bg-color-page);
}

.todo-header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 0 2px;
}

.todo-title {
  color: var(--el-text-color-primary);
  font-size: var(--ui-font-lg);
  font-weight: 700;
  letter-spacing: -.015em;
}

.todo-subtitle {
  margin-top: 2px;
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-sm);
}

.todo-progress {
  display: grid;
  grid-template-columns: auto minmax(100px, 170px) 38px;
  align-items: center;
  gap: 10px;
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-sm);
}

.todo-progress :deep(.el-progress) { width: 100%; }
.todo-progress strong {
  color: var(--el-text-color-primary);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.todo-empty {
  padding: 40px 0;
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-base);
  text-align: center;
}

.shared-data {
  flex: none;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: color-mix(in srgb, var(--el-bg-color-overlay) 86%, transparent);
  font-size: var(--ui-font-xs);
}

.shared-data :deep(.el-collapse-item__header),
.card-records :deep(.el-collapse-item__header) {
  height: 32px;
  padding: 0 10px;
  border: 0;
  background: transparent;
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-xs);
}

.shared-data :deep(.el-collapse-item__wrap),
.card-records :deep(.el-collapse-item__wrap) {
  border: 0;
  background: transparent;
}

.shared-data :deep(.el-collapse-item__content),
.card-records :deep(.el-collapse-item__content) {
  padding-bottom: 0;
  color: inherit;
  font-size: inherit;
}

.shared-record-list {
  display: grid;
  gap: 6px;
  max-height: 180px;
  overflow: auto;
  padding: 0 10px 10px;
}

.shared-record {
  display: grid;
  grid-template-columns: minmax(110px, .35fr) minmax(0, 1fr);
  gap: 10px;
  padding: 7px 8px;
  border-radius: 7px;
  background: var(--el-fill-color-light);
}

.shared-record span {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.todo-cols {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 12px;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 0 2px 8px;
  scroll-snap-type: x proximity;
  scrollbar-color: var(--el-border-color) transparent;
}

.todo-col {
  display: flex;
  flex: 0 0 280px;
  min-width: 280px;
  min-height: 0;
  overflow: hidden;
  flex-direction: column;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: color-mix(in srgb, var(--el-fill-color-light) 82%, transparent);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .025);
  scroll-snap-align: start;
}

.col-head {
  display: flex;
  flex: none;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 11px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: color-mix(in srgb, var(--el-bg-color-overlay) 72%, transparent);
}

.col-title {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--el-text-color-primary);
  font-size: var(--ui-font-base);
  font-weight: 650;
}

.col-status-icon {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border-radius: 7px;
  background: color-mix(in srgb, var(--column-color) 16%, transparent);
  color: var(--column-color);
  font-size: var(--ui-font-sm);
  font-weight: 800;
}

.col-count {
  min-width: 25px;
  height: 20px;
  justify-content: center;
  border-color: color-mix(in srgb, var(--column-color) 38%, transparent);
  color: var(--el-text-color-secondary);
}

.col-hint {
  color: var(--el-text-color-placeholder);
  font-size: var(--ui-font-xs);
}

.col-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  padding: 8px;
  scrollbar-width: thin;
}

.col-empty {
  display: grid;
  min-height: 88px;
  place-items: center;
  align-content: center;
  gap: 5px;
  border: 1px dashed var(--el-border-color);
  border-radius: 9px;
  color: var(--el-text-color-placeholder);
  font-size: var(--ui-font-sm);
}

.empty-icon {
  color: var(--column-color);
  font-size: 18px;
  opacity: .65;
}

.todo-card {
  position: relative;
  padding: 11px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-bg-color-overlay);
  box-shadow: 0 1px 2px rgba(0, 0, 0, .16), 0 4px 12px rgba(0, 0, 0, .08);
  font-size: var(--ui-font-sm);
  transition: border-color 140ms ease, box-shadow 140ms ease, transform 140ms ease;
}

.todo-card:hover {
  border-color: color-mix(in srgb, var(--column-color) 45%, var(--el-border-color));
  box-shadow: 0 3px 8px rgba(0, 0, 0, .2), 0 8px 18px rgba(0, 0, 0, .1);
  transform: translateY(-1px);
}

.card-top {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 24px;
  align-items: start;
  gap: 5px;
}

.card-content {
  color: var(--el-text-color-primary);
  font-size: var(--ui-font-base);
  font-weight: 620;
  line-height: 1.42;
  overflow-wrap: anywhere;
}

.card-menu {
  width: 24px;
  height: 24px;
  margin-top: -4px;
  opacity: 0;
  color: var(--el-text-color-secondary);
  letter-spacing: 1px;
  transition: opacity 120ms ease;
}

.todo-card:hover .card-menu,
.card-menu:focus { opacity: 1; }

.card-objective {
  display: -webkit-box;
  margin-top: 5px;
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-xs);
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.card-labels {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 9px;
}

.card-labels :deep(.el-tag) {
  height: 21px;
  border-radius: 6px;
  font-size: var(--ui-font-xs);
}

.card-records {
  margin: 9px 0 0;
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.card-records :deep(.el-collapse-item__header) { padding: 0 2px; }
.records-title { color: var(--el-text-color-secondary); }

.records-count {
  display: grid;
  min-width: 18px;
  height: 18px;
  margin-left: 6px;
  place-items: center;
  border-radius: 9px;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-xs);
}

.card-record-list {
  display: grid;
  gap: 7px;
  max-height: 180px;
  overflow: auto;
  padding: 2px 2px 8px;
}

.card-record {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: start;
  gap: 7px;
  line-height: 1.4;
}

.record-kind {
  height: 20px;
  white-space: nowrap;
}

.record-text {
  overflow-wrap: anywhere;
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-xs);
  white-space: pre-wrap;
}

.card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
}

.card-agent {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
  color: var(--el-text-color-secondary);
  font-size: var(--ui-font-xs);
}

.card-agent :deep(.el-avatar) {
  flex: none;
  background: color-mix(in srgb, var(--column-color) 22%, var(--el-fill-color));
  color: var(--column-color);
  font-size: 10px;
  font-weight: 750;
}

.card-agent span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-id {
  color: var(--el-text-color-placeholder);
  font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
  font-size: var(--ui-font-xs);
}

.col-pending { --column-color: #e6a23c; }
.col-in_progress { --column-color: #409eff; }
.col-review { --column-color: #a66cff; }
.col-completed { --column-color: #67c23a; }
.col-blocked { --column-color: #f56c6c; }

@media (max-width: 760px) {
  .todo-panel { padding: 10px 8px; }
  .todo-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }
  .todo-progress {
    width: 100%;
    grid-template-columns: auto minmax(80px, 1fr) 38px;
  }
  .todo-col {
    flex-basis: min(280px, calc(100vw - 40px));
    min-width: min(280px, calc(100vw - 40px));
  }
}
</style>
