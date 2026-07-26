<script setup lang="ts">
import { ref } from 'vue'
import type { Run } from '../types'

defineProps<{ runs: Run[]; activeId?: string }>()
const emit = defineEmits<{
  select: [id: string]
  create: []
  delete: [id: string]
  deleteWithIndex: [id: string, indexToKnowledge: boolean]
  fork: [id: string]
}>()

function relativeTime(value: string) {
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`)
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60_000))
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`
  return `${Math.floor(minutes / 1440)} 天前`
}

function statusBadge(status: string) {
  const map: Record<string, string> = { queued: 'secondary', running: 'primary', completed: 'success', failed: 'danger', cancelled: 'warning', timeout: 'warning', interrupted: 'info' }
  return map[status] || 'secondary'
}

const deleteTarget = ref<Run | null>(null)
const deleteIndexToKnowledge = ref(true)
const deleteDialogVisible = ref(false)

function requestDelete(run: Run) {
  deleteTarget.value = run
  deleteIndexToKnowledge.value = true
  deleteDialogVisible.value = true
}

function confirmDelete() {
  if (!deleteTarget.value) return
  if (deleteIndexToKnowledge.value) {
    emit('deleteWithIndex', deleteTarget.value.id, true)
  } else {
    emit('delete', deleteTarget.value.id)
  }
  deleteDialogVisible.value = false
  deleteTarget.value = null
}

function cancelDelete() {
  deleteDialogVisible.value = false
  deleteTarget.value = null
}

function requestFork(run: Run) {
  if (!window.confirm(`从"${run.objective.slice(0, 50)}"分叉出新对话分支？`)) return
  emit('fork', run.id)
}
</script>

<template>
  <div class="d-flex flex-column h-100">
    <div class="flex-grow-1 overflow-auto">
      <div v-if="runs.length === 0" class="p-3 text-secondary small text-center">还没有运行记录</div>
      <div v-for="run in runs" :key="run.id" class="border-bottom p-2 run-item"
        :class="{ 'bg-body-secondary': run.id === activeId }"
        @click="$emit('select', run.id)">
        <div class="d-flex align-items-start gap-1">
          <span :class="['me-1', 'rounded-circle', 'bg-' + statusBadge(run.status)]" style="width:8px;height:8px;display:inline-block;flex-shrink:0;margin-top:5px" />
          <div class="flex-grow-1" style="min-width:0">
            <div class="small text-truncate fw-medium">{{ run.objective }}</div>
            <small class="text-secondary">{{ relativeTime(run.created_at) }}</small>
          </div>
          <div class="d-flex gap-1 flex-shrink-0">
            <ElButton v-if="run.status === 'completed' || run.status === 'failed'"
              link size="small" class="p-0 text-secondary" title="分叉"
              @click.stop="requestFork(run)">
              <span style="font-size: var(--ui-font-md)">&#9095;</span>
            </ElButton>
            <ElButton link size="small" class="p-0 text-secondary"
              :disabled="run.status === 'queued' || run.status === 'running'"
              title="删除" @click.stop="requestDelete(run)">
              <span style="font-size: var(--ui-font-lg);font-weight:bold">&times;</span>
            </ElButton>
          </div>
        </div>
      </div>
    </div>
    <div class="border-top p-2 text-secondary small text-center">
      <span>127.0.0.1 · Local</span>
    </div>

    <!-- 删除确认对话框 -->
    <ElDialog
      v-model="deleteDialogVisible"
      title="删除对话记录"
      width="420px"
      :close-on-click-modal="false"
    >
      <div v-if="deleteTarget">
        <p style="margin-bottom:12px">
          确定删除 <strong>"{{ deleteTarget.objective.slice(0, 60) }}"</strong> 及其全部时间线记录吗？此操作无法撤销。
        </p>
        <ElCheckbox v-model="deleteIndexToKnowledge">
          先索引到知识库后再删除（保留对话内容到知识库）
        </ElCheckbox>
      </div>
      <template #footer>
        <ElButton @click="cancelDelete">取消</ElButton>
        <ElButton type="danger" @click="confirmDelete">确认删除</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.run-item { cursor: pointer; }
</style>