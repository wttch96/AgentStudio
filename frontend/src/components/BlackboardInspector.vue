<script setup lang="ts">
/**
 * BlackboardInspector — 实时查看运行中的黑板键值对。
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { api } from '../api/client'
import type { BlackboardState } from '../types'

const props = defineProps<{ runId: string | null }>()

const state = ref<BlackboardState | null>(null)
const error = ref('')
const autoRefresh = ref(true)
let timer: ReturnType<typeof setInterval> | null = null

const entries = computed(() => {
  if (!state.value) return []
  const derivedKeys = new Set(['__todos__', 'all_results', 'all_reviews', 'review_decisions'])
  return Object.values(state.value.entries)
    .filter(entry => (
      !derivedKeys.has(entry.key)
      && !/^(artifact|decision|blocker|risk|log):[^:]+:/.test(entry.key)
      && !/^(result|review):[^:]+$/.test(entry.key)
    ))
    .sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
})

watch(
  () => props.runId,
  async (id) => {
    if (id) {
      await load(id)
      if (autoRefresh.value) startPolling(id)
    } else {
      stopPolling()
      state.value = null
    }
  }
)

watch(autoRefresh, (v) => {
  if (v && props.runId) startPolling(props.runId)
  else stopPolling()
})

onUnmounted(() => stopPolling())

// ---- load / poll ----
async function load(runId: string) {
  try {
    state.value = await api.blackboard(runId)
    error.value = ''
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  }
}

function startPolling(runId: string) {
  stopPolling()
  timer = setInterval(() => load(runId), 3000)
}

function stopPolling() {
  if (timer) { clearInterval(timer); timer = null }
}

// ---- format ----
function fmt(val: unknown): string {
  if (val === null || val === undefined) return '—'
  if (typeof val === 'string') return val
  return JSON.stringify(val, null, 0)
}
</script>

<template>
  <div class="bb-inspector">
    <div class="bb-header">
      <span class="bb-title">运行共享数据</span>
      <ElSwitch v-model="autoRefresh" size="small" inline-prompt active-text="自动" inactive-text="手动" />
      <ElButton size="small" :disabled="!props.runId" @click="props.runId && load(props.runId)">刷新</ElButton>
    </div>

    <div v-if="error" class="bb-error">{{ error }}</div>

    <div v-if="!props.runId" class="bb-empty">选择运行后查看黑板状态</div>
    <div v-else-if="!entries.length" class="bb-empty">暂无任务之外的共享数据</div>

    <table v-else class="bb-table">
      <thead>
        <tr>
          <th class="col-key">Key</th>
          <th class="col-val">Value</th>
          <th class="col-by">Updated By</th>
          <th class="col-ver">Ver</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in entries" :key="e.key">
          <td class="col-key"><code>{{ e.key }}</code></td>
          <td class="col-val"><code class="val-text">{{ fmt(e.value) }}</code></td>
          <td class="col-by">{{ e.updated_by }}</td>
          <td class="col-ver">{{ e.version }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.bb-inspector {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  padding: 4px 0;
}
.bb-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.bb-title {
  font-weight: 600;
  font-size: var(--ui-font-md);
}
.bb-toggle {
  font-size: var(--ui-font-sm);
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-muted, #888);
  cursor: pointer;
}
.bb-btn {
  font-size: var(--ui-font-xs);
  padding: 2px 8px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 4px;
  background: var(--bg-secondary, #fefefe);
  cursor: pointer;
}
.bb-error { color: var(--danger, #e00); font-size: var(--ui-font-sm); }
.bb-empty { color: var(--text-muted, #888); font-size: var(--ui-font-base); text-align: center; padding: 24px 0; }

.bb-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--ui-font-sm);
  table-layout: fixed;
}
.bb-table th {
  text-align: left;
  font-weight: 600;
  padding: 6px 4px;
  border-bottom: 2px solid var(--border-color, #ddd);
  color: var(--text-muted, #888);
  font-size: var(--ui-font-xs);
}
.bb-table td {
  padding: 4px;
  border-bottom: 1px solid var(--border-light, #eee);
  vertical-align: top;
}
.col-key { width: 25%; }
.col-val { width: 45%; }
.col-by  { width: 20%; }
.col-ver { width: 10%; text-align: center; }
.val-text {
  max-height: 60px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  word-break: break-all;
}
</style>
