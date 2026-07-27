<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import MainCanvas from '../components/MainCanvas.vue'
import ThinkingTimeline from '../components/ThinkingTimeline.vue'
import DetailPanel from '../components/DetailPanel.vue'
import PromptComposer from '../components/PromptComposer.vue'
import RunSidebar from '../components/RunSidebar.vue'
import PlanBoard from '../components/PlanBoard.vue'
import StreamingChat from '../components/StreamingChat.vue'
import ConversationView from '../components/ConversationView.vue'
import AgentSequenceDiagram from '../components/AgentSequenceDiagram.vue'
import TodoPanel from '../components/TodoPanel.vue'
import { useWorkspace } from '../composables/useWorkspace'
import { useNodeGraph } from '../composables/useNodeGraph'
import { useTaskErrors } from '../composables/useTaskErrors'
import { useTimeoutDetection } from '../composables/useTimeoutDetection'
import { useInterrupt } from '../composables/useInterrupt'
import { useRunTimeline } from '../composables/useRunTimeline'
import { api } from '../api/client'
import type { Project, NodeStatus } from '../types'

const workspace = useWorkspace()
const composer = ref<InstanceType<typeof PromptComposer> | null>(null)
const showProjectDialog = ref(false)
const viewMode = ref<'dag' | 'timeline' | 'events' | 'sequence' | 'board'>('dag')

// 项目来自 workspace 全局状态
const projects = computed(() => workspace.state.projects)
const currentProject = computed(() =>
  workspace.state.projectId
    ? workspace.state.projects.find(p => p.id === workspace.state.projectId)
      || { id: workspace.state.projectId, name: workspace.state.projectName || workspace.state.projectId.slice(0, 8), root_dir: '', description: '' } as Project
    : null
)

const allEvents = computed(() => {
  const convEvents = workspace.state.conversationEvents
  return convEvents.length ? convEvents : workspace.state.events
})
const activeRunId = computed(() => workspace.state.activeRun?.id ?? null)
const activeRun = computed(() => workspace.state.activeRun)

const conversationRunsForGraph = computed(() => workspace.state.conversationRuns)
const { nodes, edges, findNode } = useNodeGraph(allEvents, activeRunId, conversationRunsForGraph)
const { errors, errorNodeIds } = useTaskErrors(allEvents)
const timeoutDetection = useTimeoutDetection(activeRun, { defaultTimeoutMs: 300_000, checkIntervalMs: 2_000 })
const { handleInterruptEvent } = useInterrupt(activeRun)
const { conversationTurns, activeAgents, memoryCompactions } = useRunTimeline(
  computed(() => workspace.state.conversationRuns),
  computed(() => workspace.state.conversationEvents),
  computed(() => workspace.state.events),
  activeRun,
)

watch([conversationTurns, activeAgents, memoryCompactions], () => {
  workspace.state.conversationTurns = conversationTurns.value
  workspace.state.activeAgents = activeAgents.value
  workspace.state.memoryCompactions = memoryCompactions.value
}, { deep: true })

const subtitle = computed(() => {
  const run = workspace.state.activeRun
  if (!run) return '描述目标，主调度器会生成任务 DAG 并调用专业 Agent。'
  const labels: Record<string, string> = {
    queued: '等待执行', running: '正在执行', completed: '执行完成',
    failed: '执行失败', cancelled: '已取消', timeout: '超时', interrupted: '已中断',
  }
  return labels[run.status] || run.status
})

async function submit(objective: string, mode?: string) {
  if (workspace.isRunning.value && objective.startsWith('/') && workspace.state.activeRun) {
    const [targetToken, ...parts] = objective.trim().split(/\s+/)
    const instruction = parts.join(' ')
    const targetName = targetToken.slice(1)
    if (!instruction) {
      workspace.state.error = `${targetToken} 后需要填写引导内容`
      return
    }
    await api.interruptRun(workspace.state.activeRun.id, {
      target: targetName === 'brain' ? 'planner' : 'agent',
      action: 'inject',
      target_agent: targetName === 'brain' ? undefined : targetName,
      instruction,
    })
    return
  }
  await workspace.createRun(objective, mode || 'auto')
}

function onProjectCreated(project: Project) {
  workspace.addProject(project)
  showProjectDialog.value = false
}

async function forkRun(sourceRunId: string) {
  try {
    const forked = await api.forkRun(sourceRunId)
    workspace.state.runs.unshift(forked as any)
    await workspace.selectRun(forked.id)
  } catch (e) {
    workspace.state.error = e instanceof Error ? e.message : '分叉失败'
  }
}

function newRun() {
  workspace.beginNewRun()
  void composer.value?.focus()
}

function clearConversation() {
  workspace.beginNewRun()
}

const selectedNodeId = computed(() => workspace.state.selectedNodeId)
const selectedNode = computed(() => selectedNodeId.value ? findNode(selectedNodeId.value) ?? null : null)

function selectNodeFn(nodeId: string) { workspace.state.selectedNodeId = nodeId }
function deselectNode() { workspace.state.selectedNodeId = null }
function updateFilter(status: NodeStatus | 'all') { workspace.state.filterStatus = status }

function handleInterruptNode(nodeId: string) {
  if (!workspace.state.activeRun) return
  void api.interruptRun(workspace.state.activeRun.id, {
    target: 'task', action: 'abort', target_task: nodeId,
  })
}

async function handleConfirmExecute() {
  if (!workspace.state.activeRun) return
  try {
    await workspace.confirmExecution(workspace.state.activeRun.id)
  } catch {
    // error surfaced via workspace state
  }
}

async function handleChatRefine(message: string) {
  if (!workspace.state.activeRun) return
  try {
    await workspace.sendChatMessage(workspace.state.activeRun.id, message)
  } catch {
    // error surfaced via workspace state
  }
}

onMounted(async () => {
  await workspace.initialize()
})
</script>

<template>
  <ElContainer class="h-100">
    <!-- Left Sidebar -->
    <ElAside width="260px" class="workspace-aside">
      <!-- Empty state when no project at all -->
      <div v-if="workspace.state.projects.length === 0" class="p-3 text-secondary small text-center flex-grow-1 d-flex align-items-center justify-content-center">
        暂无项目，请创建项目
      </div>
      <!-- No project selected but projects exist -->
      <div v-else-if="!workspace.state.projectId" class="p-3 text-secondary small text-center flex-grow-1 d-flex align-items-center justify-content-center">
        请在顶部选择项目
      </div>
      <!-- Project selected: show normal sidebar -->
      <template v-else>
      <div class="p-2 border-bottom">
        <ElButton type="primary" size="small" class="w-100" @click="newRun" :disabled="!workspace.state.projectId">＋ 新任务</ElButton>
      </div>
      <div class="p-2 border-bottom">
        <ElButton v-if="workspace.state.activeRun || workspace.state.conversationRuns.length > 0" size="small" class="w-100 mb-1" type="danger" plain @click="clearConversation">清空对话</ElButton>
      </div>
      <RunSidebar
        :runs="workspace.state.runs"
        :active-id="workspace.state.activeRun?.id"
        @select="workspace.selectRun"
        @create="newRun"
        @delete="(id: string) => workspace.deleteRun(id)"
        @delete-with-index="(id: string, index: boolean) => workspace.deleteRun(id, index)"
        @fork="forkRun"
      />
      </template>
    </ElAside>

    <!-- Main Content -->
    <ElMain class="workspace-main">
      <!-- Error banner -->
      <ElAlert v-if="workspace.state.error" type="error" class="m-2" closable @close="workspace.state.error = ''">
        <template #title>
          <strong>出错</strong> {{ workspace.state.error }}
        </template>
      </ElAlert>

      <!-- No project at all -->
      <div v-if="workspace.state.projects.length === 0" class="welcome-center">
        <div class="text-center p-5">
          <div style="font-size:48px;margin-bottom:12px">&#128230;</div>
          <h2>欢迎使用 Agent Studio</h2>
          <p class="text-secondary">创建项目来配置 Agent 团队。</p>
          <ElButton type="primary" @click="showProjectDialog = true">创建项目</ElButton>
        </div>
      </div>

      <!-- No project selected -->
      <div v-else-if="!workspace.state.projectId" class="welcome-center">
        <div class="text-center p-5">
          <div style="font-size:48px;margin-bottom:12px">&#128209;</div>
          <h2>尚未选择项目</h2>
          <p class="text-secondary">请在顶部 Header 中选择一个项目，然后开始对话。</p>
        </div>
      </div>

      <template v-else>
        <!-- Loading -->
        <div v-if="workspace.state.loading" class="welcome-center">
          <div class="d-flex align-items-center gap-2">
            <ElIcon class="is-loading"><Loading /></ElIcon>
            正在连接本地调度器&hellip;
          </div>
        </div>

        <!-- No active run: welcome -->
        <div v-if="!workspace.state.activeRun && !workspace.state.loading" class="welcome-area">
          <div class="p-4">
            <div class="d-flex gap-2 mb-2">
              <ElTag type="info">{{ currentProject?.name }}</ElTag>
            </div>
            <h1 style="font-size:1.5rem;font-weight:600">今天想让 Agent 团队完成什么？</h1>
            <p class="text-secondary">{{ subtitle }}</p>
            <div class="d-flex gap-2 mt-3">
              <ElButton plain @click="submit('分析当前项目，并制定前后端下一阶段的实现计划')">
                分析项目并制定计划
              </ElButton>
              <ElButton plain @click="submit('检查当前代码质量，分别执行前端和后端审查')">
                并行审查前后端代码
              </ElButton>
            </div>
          </div>
          <PlanBoard v-if="workspace.plan.value.length" :tasks="workspace.plan.value" :events="allEvents" :can-retry="false" :contract="workspace.planContract.value" class="flex-grow-1" />
        </div>

        <!-- Active run: view toggle + canvas/timeline -->
        <div v-if="workspace.state.activeRun" class="canvas-area">
          <div class="d-flex align-items-center gap-1 px-2 py-1 border-bottom">
            <ElButton size="small" :type="viewMode === 'dag' ? 'primary' : ''" @click="viewMode = 'dag'">DAG 图</ElButton>
            <ElButton size="small" :type="viewMode === 'timeline' ? 'primary' : ''" @click="viewMode = 'timeline'">时间轴</ElButton>
            <ElButton size="small" :type="viewMode === 'events' ? 'primary' : ''" @click="viewMode = 'events'">事件记录</ElButton>
            <ElButton size="small" :type="viewMode === 'sequence' ? 'primary' : ''" @click="viewMode = 'sequence'">时序图</ElButton>
            <ElButton size="small" :type="viewMode === 'board' ? 'primary' : ''" @click="viewMode = 'board'">看板</ElButton>
          </div>
          <MainCanvas
            v-if="viewMode === 'dag'"
            :nodes="nodes"
            :edges="edges"
            :selected-node-id="selectedNodeId"
            :filter-status="workspace.state.filterStatus"
            :is-running="workspace.isRunning.value"
            :active-run-objective="workspace.state.activeRun?.objective || ''"
            :streaming-thinking="workspace.state.streamingState.thinkingText"
            :streaming-response="workspace.state.streamingState.responseText"
            :is-streaming="workspace.state.streamingState.isStreaming"
            @select-node="selectNodeFn"
            @interrupt-node="handleInterruptNode"
            @update-filter="updateFilter"
          />
          <ThinkingTimeline
            v-else-if="viewMode === 'timeline'"
            :tasks="workspace.plan.value"
            :events="allEvents"
            :turns="conversationTurns"
            :memory-compactions="memoryCompactions"
          />
          <ConversationView
            v-else-if="viewMode === 'events'"
            :events="allEvents"
            :final-answer="workspace.state.activeRun?.final_answer ?? null"
          />
          <AgentSequenceDiagram
            v-else-if="viewMode === 'sequence'"
            :tasks="workspace.plan.value"
            :events="allEvents"
          />
          <div v-else class="board-workspace">
            <TodoPanel
              :run-id="activeRunId"
              :tasks="workspace.plan.value"
              :events="allEvents"
            />
          </div>
        </div>

        <!-- Bottom composer -->
        <PromptComposer
          ref="composer"
          :submitting="workspace.state.submitting"
          :is-running="workspace.isRunning.value"
          :is-awaiting-confirmation="workspace.isAwaitingConfirmation.value"
          :queue-items="workspace.state.taskQueue"
          :active-agents="activeAgents"
          :active-run-id="workspace.state.activeRun?.id ?? null"
          :agents="workspace.state.agents"
          @submit="submit"
          @interrupt="workspace.cancelActiveRun()"
          @promote-queue="workspace.promoteQueueItem"
          @remove-queue="workspace.removeFromQueue"
          @confirm-execute="handleConfirmExecute"
          @chat-refine="handleChatRefine"
          @interrupt-agent="(agent: string, action: string, instruction?: string) => {
            if (workspace.state.activeRun) {
              api.interruptRun(workspace.state.activeRun.id, {
                target: agent === 'all' ? 'all' : 'agent',
                action: action as any,
                target_agent: agent !== 'all' ? agent : undefined,
                instruction: instruction || '',
              })
            }
          }"
        />
      </template>
    </ElMain>

    <!-- Right detail panel -->
    <DetailPanel
      v-if="selectedNode"
      :selected-node="selectedNode"
      :is-running="workspace.isRunning.value"
      @close="deselectNode"
      @interrupt-node="handleInterruptNode"
    />

    <!-- Project dialog -->
    <ProjectDialog
      v-if="showProjectDialog"
      :projects="projects"
      @created="onProjectCreated"
      @close="showProjectDialog = false; workspace.refreshConfiguration()"
    />
  </ElContainer>
</template>

<style scoped>
.workspace-aside {
  border-right: 1px solid var(--el-border-color-light);
  display: flex;
  flex-direction: column;
}
.workspace-main {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
}
.welcome-center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.welcome-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}
.canvas-area {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.canvas-area > :nth-child(2) {
  flex: 1;
  overflow-y: auto;
}
.board-workspace {
  padding: 12px;
  overflow: auto;
}
</style>
