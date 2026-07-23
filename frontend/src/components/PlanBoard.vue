<script setup lang="ts">
import type { PlanTask, RunEvent } from '../types'

const props = defineProps<{
  tasks: PlanTask[]
  events: RunEvent[]
  canRetry: boolean
  contract: string
}>()
defineEmits<{ retry: [taskId: string] }>()

const agentEventTypes = new Set([
  'agent.started',
  'agent.message',
  'tool.started',
  'skill.loaded',
  'agent.completed',
  'agent.failed',
])

function taskEvents(taskId: string) {
  return props.events.filter(
    (event) => event.task_id === taskId && agentEventTypes.has(event.type),
  )
}

function taskStatus(taskId: string) {
  const events = taskEvents(taskId)
  if (events.some((event) => event.type === 'agent.failed')) return 'failed'
  if (events.some((event) => event.type === 'agent.completed')) return 'completed'
  if (events.some((event) => event.type === 'agent.started')) return 'running'
  return 'pending'
}

/** 利用 agent.started / agent.completed / agent.failed 事件的时间戳计算耗时文本。 */
function taskTimingText(taskId: string) {
  const events = taskEvents(taskId)
  const status = taskStatus(taskId)
  if (status === 'pending') return ''
  const started = events.find(e => e.type === 'agent.started')
  if (!started) return '--'
  const startedAt = new Date(started.timestamp).getTime()
  if (status === 'completed') {
    const completed = events.find(e => e.type === 'agent.completed')
    if (completed) {
      const duration = ((new Date(completed.timestamp).getTime() - startedAt) / 1000).toFixed(1)
      return `${duration}s`
    }
    return '--'
  }
  if (status === 'failed') {
    const failedEv = events.find(e => e.type === 'agent.failed')
    if (failedEv) {
      const duration = ((new Date(failedEv.timestamp).getTime() - startedAt) / 1000).toFixed(1)
      return `${duration}s · 失败`
    }
    return '--'
  }
  // running — PlanBoard 没有 live timer，用已记录耗时
  const lastEvent = events.at(-1)
  if (lastEvent) {
    const duration = ((new Date(lastEvent.timestamp).getTime() - startedAt) / 1000).toFixed(1)
    return `进行中 · ${duration}s`
  }
  return '--'
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
        <div v-if="taskTimingText(task.id)" class="task-timing">{{ taskTimingText(task.id) }}</div>
      </article>
    </div>
  </section>
</template>
