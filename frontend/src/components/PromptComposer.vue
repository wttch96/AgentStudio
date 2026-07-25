<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { api } from '../api/client'
import type { ActiveAgent, FlowDefinition } from '../types'

const props = defineProps<{
  submitting: boolean; autofocus?: boolean; isRunning: boolean
  queueItems: { id: string; objective: string }[]
  activeAgents: ActiveAgent[]; activeRunId: string | null
}>()
const emit = defineEmits<{
  submit: [objective: string]; interrupt: []
  promoteQueue: [qid: string]; removeQueue: [qid: string]
  interruptAgent: [agent: string, action: string, instruction?: string]
}>()

const objective = ref('')
const input = ref<InstanceType<typeof HTMLTextAreaElement> | any>(null)
const showInterruptMenu = ref(false)
const showInjectPopup = ref(false)
const injectTarget = ref('all')
const injectInstruction = ref('')

const commandOptions = [
  { command: '/+', label: '执行预定义流程 (用法: /+流程名)', isFlow: true },
  { command: '/agent', label: '指定 Agent 并传递引导指令' },
  { command: '/frontend', label: '快捷引导 vue-frontend' },
  { command: '/backend', label: '快捷引导 flask-backend' },
  { command: '/retry', label: '重试失败节点' },
]
const flowOptions = ref<Array<{ command: string; label: string; isFlow: boolean }>>([])
const loadingFlows = ref(false)

async function fetchFlows() {
  if (loadingFlows.value) return; loadingFlows.value = true
  try {
    const items = await api.flows()
    flowOptions.value = items.map((f: FlowDefinition) => ({
      command: `/+${f.name}`, label: `${f.description} (v${f.version})`, isFlow: true,
    }))
  } catch { flowOptions.value = [] }
  finally { loadingFlows.value = false }
}

const visibleCommands = computed(() => {
  const value = objective.value.trim().toLowerCase()
  if (!value.startsWith('/') || value.includes(' ')) return []
  if (value.startsWith('/+')) { fetchFlows(); return flowOptions.value.filter(i => i.command.startsWith(value)) }
  return commandOptions.filter(i => i.command.startsWith(value))
})

async function submit() {
  const value = objective.value.trim()
  if (!value || props.submitting) return
  emit('submit', value); objective.value = ''
}
function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void submit() }
}
async function focus() { await nextTick(); input.value?.focus() }
async function chooseCommand(command: string) { objective.value = `${command} `; await focus() }
defineExpose({ focus })

function handleInterruptAction(agent: string, action: string) {
  if (action === 'inject') { injectTarget.value = agent; showInjectPopup.value = true; showInterruptMenu.value = false; return }
  emit('interruptAgent', agent, action); showInterruptMenu.value = false
}
function sendInjectInstruction() {
  if (!injectInstruction.value.trim()) return
  emit('interruptAgent', injectTarget.value, 'inject', injectInstruction.value.trim())
  injectInstruction.value = ''; showInjectPopup.value = false
}
function onInterruptBlur() { setTimeout(() => { if (showInterruptMenu.value) showInterruptMenu.value = false }, 150) }
</script>

<template>
  <div class="border-top bg-body-tertiary p-2 position-relative">
    <!-- Command menu -->
    <div v-if="visibleCommands.length" class="position-absolute bottom-100 start-0 end-0 mb-1 mx-2 bg-body border rounded shadow-sm p-1" style="z-index:10">
      <ElButton v-for="item in visibleCommands" :key="item.command" link size="small"
        class="d-block w-100 text-start" @click="chooseCommand(item.command)">
        <strong>{{ item.command }}</strong> <small class="text-secondary">{{ item.label }}</small>
      </ElButton>
    </div>

    <!-- Queue -->
    <div v-if="queueItems.length" class="mb-1">
      <div class="d-flex justify-content-between small text-secondary mb-1">
        <span>待执行队列 ({{ queueItems.length }})</span>
        <span>点击 ↑ 优先 · × 移除</span>
      </div>
      <div v-for="q in queueItems" :key="q.id" class="d-flex align-items-center gap-2 p-1 border rounded mb-1 small bg-body">
        <ElTag type="info" size="small" round>{{ queueItems.indexOf(q) + 1 }}</ElTag>
        <span class="flex-grow-1 text-truncate">{{ q.objective.slice(0, 80) }}</span>
        <ElButton link size="small" class="p-0 text-primary" title="优先" @click="$emit('promoteQueue', q.id)">&#8593;</ElButton>
        <ElButton link size="small" class="p-0 text-danger" title="移除" @click="$emit('removeQueue', q.id)">&times;</ElButton>
      </div>
    </div>

    <!-- Inject popup -->
    <div v-if="showInjectPopup" class="position-absolute bottom-100 start-0 end-0 mb-1 mx-2 p-2 bg-body border rounded shadow" style="z-index:10">
      <div class="d-flex justify-content-between mb-1">
        <strong class="small">注入指令到 {{ injectTarget === 'all' ? '全部 Agent' : injectTarget }}</strong>
        <ElButton :icon="Close" circle size="small" @click="showInjectPopup = false" />
      </div>
      <ElInput v-model="injectInstruction" type="textarea" :rows="3" size="small" class="mb-1" placeholder="输入引导指令…" @keydown.enter.exact.prevent="sendInjectInstruction" />
      <div class="d-flex justify-content-end gap-1">
        <ElButton size="small" @click="showInjectPopup = false">取消</ElButton>
        <ElButton type="primary" size="small" :disabled="!injectInstruction.trim()" @click="sendInjectInstruction">发送指令</ElButton>
      </div>
    </div>

    <!-- Textarea -->
    <ElInput ref="input" v-model="objective" type="textarea" :rows="3" maxlength="20000" class="mb-1"
      :placeholder="isRunning ? '任务执行中，输入引导指令加入队列…' : '描述你希望多个 Agent 完成的任务…'"
      aria-label="任务目标" @keydown="handleKeydown" />

    <!-- Toolbar -->
    <div class="d-flex justify-content-between align-items-center">
      <div class="small text-secondary">
        <template v-if="isRunning">
          <span class="d-inline-block rounded-circle bg-primary me-1" style="width:7px;height:7px;animation:pulse-dot 1.5s ease-in-out infinite" />
          任务执行中 · {{ activeAgents.length }} 个 Agent 活跃
        </template>
        <template v-else><kbd>/</kbd> 选择 Agent · <kbd>Enter</kbd> 发送</template>
      </div>

      <div class="d-flex gap-1">
        <!-- Interrupt -->
        <div v-if="isRunning" class="position-relative">
          <ElButton type="danger" size="small" plain @click="showInterruptMenu = !showInterruptMenu" @blur="onInterruptBlur">中断</ElButton>
          <div v-if="showInterruptMenu" class="position-absolute bottom-100 end-0 mb-1 bg-body border rounded shadow-sm" style="min-width:220px;z-index:20">
            <div class="px-2 py-1 small text-secondary">暂停执行</div>
            <ElButton link size="small" class="d-block w-100 text-start" @click="handleInterruptAction('all', 'pause')">&#9208; 暂停全部 Agent</ElButton>
            <ElButton v-for="a in activeAgents" :key="a.name" link size="small" class="d-block w-100 text-start" @click="handleInterruptAction(a.name, 'pause')">
              &#9208; 暂停 {{ a.name }} <small class="text-secondary">{{ a.title }}</small>
            </ElButton>
            <hr class="my-1" />
            <div class="px-2 py-1 small text-secondary">注入指令</div>
            <ElButton link size="small" class="d-block w-100 text-start" @click="handleInterruptAction('all', 'inject')">&#128172; 注入指令到全部</ElButton>
            <hr class="my-1" />
            <ElButton link size="small" class="d-block w-100 text-start" @click="handleInterruptAction('all', 'replan')">&#128260; 触发重规划</ElButton>
            <ElButton type="danger" size="small" class="d-block w-100" @click="$emit('interrupt'); showInterruptMenu = false">&#9209; 中止运行</ElButton>
          </div>
        </div>
        <ElButton type="primary" size="small" :disabled="!objective.trim() || submitting" @click="submit">
          {{ submitting ? '创建中…' : isRunning ? '加入队列 ▲' : '运行 ▲' }}
        </ElButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }
</style>
