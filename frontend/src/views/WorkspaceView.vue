<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import MainCanvas from '../components/MainCanvas.vue'
import ThinkingTimeline from '../components/ThinkingTimeline.vue'
import DetailPanel from '../components/DetailPanel.vue'
import PromptComposer from '../components/PromptComposer.vue'
import RunSidebar from '../components/RunSidebar.vue'
import ProjectDialog from '../components/ProjectDialog.vue'
import PlanBoard from '../components/PlanBoard.vue'
import StreamingChat from '../components/StreamingChat.vue'
import ConversationView from '../components/ConversationView.vue'
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
const viewMode = ref<'dag' | 'timeline'>('dag')

const projects = ref<Project[]>([])
const currentProject = ref<Project | null>(null)

async function loadProjects() {
  try { projects.value = (await api.projects()).items } catch { /* */ }
}

function applyProject(p: Project) {
  workspace.state.projectId = p.id
  workspace.state.projectName = p.name
}

function selectProject(p: Project) {
  currentProject.value = p
  applyProject(p)
  showProjectDialog.value = false
  workspace.refreshConfiguration()
}

function onProjectCreated(p: Project) {
  projects.value = [p, ...projects.value]
  currentProject.value = p
  applyProject(p)
  showProjectDialog.value = false
  workspace.refreshConfiguration()
}

watch(currentProject, (p) => { if (p) applyProject(p) })

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
const { interruptState, pauseAll, pauseAgent, injectGuidance, abortRun, handleInterruptEvent } = useInterrupt(activeRun)
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

async function submit(objective: string) {
  await workspace.createRun(objective)
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

const selectedNodeId = computed(() => workspace.state.selectedNodeId)
const selectedNode = computed(() => selectedNodeId.value ? findNode(selectedNodeId.value) ?? null : null)

function selectNode(nodeId: string) { workspace.state.selectedNodeId = nodeId }
function deselectNode() { workspace.state.selectedNodeId = null }
function updateFilter(status: NodeStatus | 'all') { workspace.state.filterStatus = status }

function handleInterruptNode(nodeId: string) {
  const node = findNode(nodeId)
  if (node?.agentId) void pauseAgent(node.agentId)
}

function handleInjectGuidance(nodeId: string, instruction: string) {
  void injectGuidance(findNode(nodeId)?.agentId ?? null, instruction)
}

onMounted(async () => {
  await loadProjects()
  if (projects.value.length > 0) {
    currentProject.value = projects.value[0]
    applyProject(projects.value[0])
  }
  await workspace.initialize()
})
</script>

<template>
  <ElContainer class="h-100">
    <!-- Left Sidebar -->
    <ElAside width="260px" class="workspace-aside">
      <div class="p-2 border-bottom">
        <ElButton type="primary" size="small" class="w-100" @click="newRun">＋ 新任务</ElButton>
      </div>
      <div class="p-2 border-bottom">
        <ElButton size="small" class="w-100" @click="showProjectDialog = true">
          {{ currentProject?.name || '选择项目' }}
        </ElButton>
      </div>
      <RunSidebar
        :runs="workspace.state.runs"
        :active-id="workspace.state.activeRun?.id"
        @select="workspace.selectRun"
        @create="newRun"
        @delete="workspace.deleteRun"
        @fork="forkRun"
      />
    </ElAside>

    <!-- Main Content -->
    <ElMain class="workspace-main">
      <!-- Error banner -->
      <ElAlert v-if="workspace.state.error" type="error" class="m-2" closable @close="workspace.state.error = ''">
        <template #title>
          <strong>出错</strong> {{ workspace.state.error }}
        </template>
      </ElAlert>

      <!-- No project -->
      <div v-if="!currentProject" class="welcome-center">
        <div class="text-center p-5">
          <div style="font-size:48px;margin-bottom:12px">&#128230;</div>
          <h2>欢迎使用 Agent Studio</h2>
          <p class="text-secondary">选择一个项目开始，或创建新项目来配置 Agent 团队。</p>
          <ElButton type="primary" @click="showProjectDialog = true">创建或选择项目</ElButton>
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
            <ElTag type="info" class="mb-2">{{ currentProject.name }}</ElTag>
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
            @select-node="selectNode"
            @interrupt-node="handleInterruptNode"
            @update-filter="updateFilter"
          />
          <ThinkingTimeline
            v-else
            :tasks="workspace.plan.value"
            :events="allEvents"
            :turns="conversationTurns"
            :memory-compactions="memoryCompactions"
          />
        </div>

        <!-- Conversation history + Streaming -->
        <div v-if="allEvents.length" class="border-top overflow-auto" style="max-height:50vh;min-height:120px">
          <ConversationView
            :events="allEvents"
            :final-answer="workspace.state.activeRun?.final_answer ?? null"
          />
          <StreamingChat
            v-if="conversationTurns.length"
            :turns="conversationTurns"
            :events="allEvents"
            :streaming="workspace.state.streamingState"
            :active-run-id="workspace.state.activeRun?.id ?? null"
            :is-running="workspace.isRunning.value"
            @fork="forkRun"
          />
        </div>

        <!-- Bottom composer -->
        <PromptComposer
          ref="composer"
          :submitting="workspace.state.submitting"
          :is-running="workspace.isRunning.value"
          :queue-items="workspace.state.taskQueue"
          :active-agents="activeAgents"
          :active-run-id="workspace.state.activeRun?.id ?? null"
          @submit="submit"
          @interrupt="workspace.cancelActiveRun()"
          @promote-queue="workspace.promoteQueueItem"
          @remove-queue="workspace.removeFromQueue"
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
      @inject-guidance="handleInjectGuidance"
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
</style>
