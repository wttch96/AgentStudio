<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import MainCanvas from './components/MainCanvas.vue'
import DetailPanel from './components/DetailPanel.vue'
import AppHeader from './components/AppHeader.vue'
import DagModal from './components/DagModal.vue'
import PromptComposer from './components/PromptComposer.vue'
import RunSidebar from './components/RunSidebar.vue'
import ConfigCenter from './components/config/ConfigCenter.vue'
import ProjectDialog from './components/ProjectDialog.vue'
import { useWorkspace } from './composables/useWorkspace'
import { useNodeGraph } from './composables/useNodeGraph'
import { useTaskErrors } from './composables/useTaskErrors'
import { useTimeoutDetection } from './composables/useTimeoutDetection'
import { useInterrupt } from './composables/useInterrupt'
import { useRunTimeline } from './composables/useRunTimeline'
import { api } from './api/client'
import type { Project, NodeStatus } from './types'

const workspace = useWorkspace()
const composer = ref<InstanceType<typeof PromptComposer> | null>(null)
const showConfiguration = ref(false)
const showProjectDialog = ref(false)
const leftPanelOpen = ref(true)
const rightPanelOpen = ref(true)
const showDagModal = ref(false)

// Project state
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
  projects.value.unshift(p)
  currentProject.value = p
  applyProject(p)
  showProjectDialog.value = false
  workspace.refreshConfiguration()
}

watch(currentProject, (p) => {
  if (p) applyProject(p)
})

// ==================== 新 composables ====================

// 计算属性提供响应式依赖给 composables
const allEvents = computed(() => {
  const convEvents = workspace.state.conversationEvents
  return convEvents.length ? convEvents : workspace.state.events
})
const activeRunId = computed(() => workspace.state.activeRun?.id ?? null)
const activeRun = computed(() => workspace.state.activeRun)

// 节点图
const { nodes, edges, findNode } = useNodeGraph(allEvents, activeRunId)

// 错误
const { errors, errorNodeIds } = useTaskErrors(allEvents)

// 超时检测
const timeoutDetection = useTimeoutDetection(activeRun, {
  defaultTimeoutMs: 300_000, // 5 分钟默认
  checkIntervalMs: 2_000,
})

// 中断
const { interruptState, pauseAll, pauseAgent, injectGuidance, abortRun, handleInterruptEvent, reset: resetInterrupt } = useInterrupt(activeRun)

// 对话时间线
const { conversationTurns, activeAgents, memoryCompactions, planTasks, planContract } = useRunTimeline(
  computed(() => workspace.state.conversationRuns),
  computed(() => workspace.state.conversationEvents),
  computed(() => workspace.state.events),
  activeRun,
)

// 同步派生状态到 workspace（兼容旧代码）
watch([conversationTurns, activeAgents, memoryCompactions], () => {
  workspace.state.conversationTurns = conversationTurns.value
  workspace.state.activeAgents = activeAgents.value
  workspace.state.memoryCompactions = memoryCompactions.value
}, { deep: true })

// 将超时节点同步到使用 useNodeGraph 的节点
// ... timeout integration handled in MainCanvas

// ==================== 事件处理 ====================

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

async function configurationSaved() {
  await workspace.refreshConfiguration()
}

// ==================== 节点交互 ====================

const selectedNodeId = computed(() => workspace.state.selectedNodeId)
const selectedNode = computed(() => {
  if (!selectedNodeId.value) return null
  return findNode(selectedNodeId.value) ?? null
})

function selectNode(nodeId: string) {
  workspace.state.selectedNodeId = nodeId
}
function deselectNode() {
  workspace.state.selectedNodeId = null
}

function updateFilter(status: NodeStatus | 'all') {
  workspace.state.filterStatus = status
}

function handleInterruptNode(nodeId: string) {
  const node = findNode(nodeId)
  if (node?.agentId) {
    void pauseAgent(node.agentId)
  }
}

function handleInjectGuidance(nodeId: string, instruction: string) {
  const node = findNode(nodeId)
  void injectGuidance(node?.agentId ?? null, instruction)
}

// DAG 统计
const dagStats = computed(() => {
  const tasks = planTasks.value
  const turns = conversationTurns.value
  return `${turns.length}轮 ${tasks.length}任务`
})

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
  <div
    class="app-shell"
    :class="{ 'left-panel-closed': !leftPanelOpen, 'right-panel-closed': !rightPanelOpen }"
  >
    <AppHeader
      :status="workspace.state.status"
      :left-panel-open="leftPanelOpen"
      :right-panel-open="rightPanelOpen"
      :project-name="currentProject?.name"
      :is-running="workspace.isRunning.value"
      @toggle-left="leftPanelOpen = !leftPanelOpen"
      @toggle-right="rightPanelOpen = !rightPanelOpen"
      @configure="showConfiguration = true"
      @switch-project="showProjectDialog = true"
      @interrupt="abortRun"
    />
    <RunSidebar
      :runs="workspace.state.runs"
      :active-id="workspace.state.activeRun?.id"
      @select="workspace.selectRun"
      @create="newRun"
      @delete="workspace.deleteRun"
      @fork="forkRun"
    />

    <main class="workspace">
      <div v-if="workspace.state.error" class="error-banner" role="alert">
        <strong>出错</strong>
        <span>{{ workspace.state.error }}</span>
        <button type="button" class="error-dismiss" @click="workspace.state.error = ''" title="关闭">×</button>
      </div>

      <!-- No project selected -->
      <template v-if="!currentProject">
        <section class="welcome-panel">
          <div class="welcome-symbol">📦</div>
          <h2>欢迎使用 Agent Studio</h2>
          <p>选择一个项目开始，或创建新项目来配置 Agent 团队。</p>
          <div class="suggestion-grid">
            <button type="button" @click="showProjectDialog = true">创建或选择项目</button>
          </div>
        </section>
      </template>

      <!-- Has project -->
      <template v-else>
        <!-- Loading -->
        <div v-if="workspace.state.loading" class="loading-state">
          <span class="loading-orb" /> 正在连接本地调度器…
        </div>

        <!-- 无活跃运行：欢迎页 -->
        <template v-if="!workspace.state.activeRun">
          <div class="workspace-heading">
            <div>
              <span class="eyebrow">{{ currentProject.name }}</span>
              <h1>今天想让 Agent 团队完成什么？</h1>
              <p>{{ subtitle }}</p>
            </div>
          </div>

          <!-- 欢迎区不显示画布，直接显示提示 -->
          <section class="welcome-panel" style="min-height:120px">
            <div class="suggestion-grid">
              <button type="button" @click="submit('分析当前项目，并制定前后端下一阶段的实现计划')">分析项目并制定计划</button>
              <button type="button" @click="submit('检查当前代码质量，分别执行前端和后端审查')">并行审查前后端代码</button>
            </div>
          </section>
        </template>

        <!-- 有活跃运行：三列布局 -->
        <template v-else>
          <div class="workspace-content">
            <!-- 中间：画布 -->
            <MainCanvas
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
              @toggle-dag-modal="showDagModal = true"
            />
          </div>

          <!-- DAG 按钮 + 停止按钮 -->
          <div class="run-status-bar">
            <div class="run-status-left">
              <span class="eyebrow">
                {{ workspace.state.activeRun.objective.slice(0, 60) }}{{ workspace.state.activeRun.objective.length > 60 ? '…' : '' }}
              </span>
            </div>
            <div class="run-status-right">
              <button type="button" class="dag-trigger-btn" @click="showDagModal = true" title="全屏 DAG 视图">
                <span aria-hidden="true">◇</span> DAG
                <span class="dag-trigger-badge">{{ dagStats }}</span>
              </button>
              <button class="stop-button" type="button" @click="workspace.cancelActiveRun()">
                <span aria-hidden="true">■</span> 停止任务
              </button>
            </div>
          </div>
        </template>

        <!-- 底部输入框始终存在 -->
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
    </main>

    <!-- 右侧详情面板 -->
    <DetailPanel
      v-if="selectedNode"
      :selected-node="selectedNode"
      :is-running="workspace.isRunning.value"
      @close="deselectNode"
      @interrupt-node="handleInterruptNode"
      @inject-guidance="handleInjectGuidance"
    />

    <ConfigCenter
      v-if="showConfiguration"
      :agents="workspace.state.agents"
      :skills="workspace.state.skills"
      :project-id="currentProject?.id || ''"
      @close="showConfiguration = false"
      @saved="configurationSaved"
    />

    <ProjectDialog
      v-if="showProjectDialog"
      :projects="projects"
      @created="onProjectCreated"
      @close="showProjectDialog = false; workspace.refreshConfiguration()"
    />

    <!-- DAG Modal -->
    <DagModal
      :visible="showDagModal"
      :tasks="planTasks"
      :events="[...workspace.state.conversationEvents, ...workspace.state.events]"
      :contract="planContract"
      :turns="conversationTurns"
      :memory-compactions="memoryCompactions"
      @close="showDagModal = false"
    />
  </div>
</template>

<style scoped>
/* 工作区内容（中间列 + 右侧面板） */
.workspace-content {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 0;
}

/* Run status bar */
.run-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: var(--content-width);
  margin: 0 auto 0.25rem;
  width: 100%;
  flex-shrink: 0;
  overflow: hidden;
}

.run-status-left {
  display: flex;
  align-items: center;
}

.run-status-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* DAG trigger button */
.dag-trigger-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border: 1px solid rgba(10, 132, 255, 0.25);
  border-radius: 8px;
  background: rgba(10, 132, 255, 0.08);
  color: #64d2ff;
  font-size: 0.65rem;
  font-weight: 550;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.dag-trigger-btn:hover {
  background: rgba(10, 132, 255, 0.16);
  border-color: rgba(10, 132, 255, 0.45);
}

.dag-trigger-badge {
  font-size: 0.5rem;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(10, 132, 255, 0.15);
  color: #64d2ff;
}
</style>
