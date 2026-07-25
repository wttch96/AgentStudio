<script setup lang="ts">
import type { NodeStatus } from '../types'

defineProps<{
  filterStatus: NodeStatus | 'all'
  counts: {
    all: number
    running: number
    completed: number
    failed: number
  }
}>()

const emit = defineEmits<{
  updateFilter: [status: NodeStatus | 'all']
}>()

const filters: Array<{ key: NodeStatus | 'all'; label: string; icon: string }> = [
  { key: 'all', label: '全部', icon: '⊡' },
  { key: 'running', label: '运行中', icon: '●' },
  { key: 'completed', label: '已完成', icon: '✓' },
  { key: 'failed', label: '失败', icon: '✕' },
]
</script>

<template>
  <div class="filter-bar">
    <button
      v-for="f in filters"
      :key="f.key"
      type="button"
      class="filter-btn"
      :class="{ active: filterStatus === f.key }"
      @click="emit('updateFilter', f.key)"
    >
      <span class="filter-icon">{{ f.icon }}</span>
      <span class="filter-label">{{ f.label }}</span>
      <span class="filter-count">{{ counts[f.key] || 0 }}</span>
    </button>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
  padding: 2px;
  margin-bottom: 6px;
  border-radius: 8px;
  background: rgba(118, 118, 128, 0.08);
}

.filter-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  padding: 4px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--secondary);
  cursor: pointer;
  font-size: 0.5625rem;
  font-weight: 500;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.filter-btn:hover {
  color: var(--label);
  background: rgba(255, 255, 255, 0.04);
}

.filter-btn.active {
  background: rgba(10, 132, 255, 0.12);
  color: #64d2ff;
}

.filter-icon {
  font-size: 0.5rem;
}

.filter-label {
  flex: 0 0 auto;
}

.filter-count {
  font-size: 0.4375rem;
  padding: 1px 4px;
  border-radius: 999px;
  background: rgba(118, 118, 128, 0.15);
  min-width: 16px;
  text-align: center;
}

.filter-btn.active .filter-count {
  background: rgba(10, 132, 255, 0.2);
  color: #64d2ff;
}
</style>
