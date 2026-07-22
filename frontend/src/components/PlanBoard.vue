<script setup lang="ts">
import type { PlanTask, RunEvent } from '../types'

const props = defineProps<{
  tasks: PlanTask[]
  events: RunEvent[]
  canRetry: boolean
  contract: string
}>()
defineEmits<{ retry: [taskId: string] }>()

function taskStatus(taskId: string) {
  const taskEvents = props.events.filter((event) => event.task_id === taskId)
  if (taskEvents.some((event) => event.type === 'agent.failed')) return 'failed'
  if (taskEvents.some((event) => event.type === 'agent.completed')) return 'completed'
  if (taskEvents.some((event) => event.type === 'agent.started')) return 'running'
  return 'pending'
}
</script>

<template>
  <section v-if="tasks.length" class="plan-board">
    <div class="section-title">
      <span class="eyebrow">任务 DAG</span>
      <span>{{ tasks.length }} 个节点</span>
    </div>
    <details v-if="contract" class="coordination-contract" open>
      <summary>DeepSeek 共享接口 / 协议契约</summary>
      <pre>{{ contract }}</pre>
    </details>
    <div class="plan-grid">
      <article v-for="task in tasks" :key="task.id" class="plan-task" :class="taskStatus(task.id)">
        <div class="plan-task-top">
          <span class="task-state-icon" aria-hidden="true" />
          <strong>{{ task.title }}</strong>
        </div>
        <div class="agent-label">{{ task.agent }}</div>
        <div class="task-command-row">
          <code>{{ task.id }}</code>
          <button
            v-if="taskStatus(task.id) === 'failed'"
            type="button"
            :disabled="!canRetry"
            @click="$emit('retry', task.id)"
          >
            重试
          </button>
        </div>
        <div v-if="task.depends_on.length" class="dependency-label">
          依赖 {{ task.depends_on.join('、') }}
        </div>
      </article>
    </div>
  </section>
</template>
