<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AgentInspector from './components/AgentInspector.vue'
import AppHeader from './components/AppHeader.vue'
import DagGraph from './components/DagGraph.vue'
import StreamingChat from './components/StreamingChat.vue'
import ThinkingTimeline from './components/ThinkingTimeline.vue'
import PromptComposer from './components/PromptComposer.vue'
import RunSidebar from './components/RunSidebar.vue'
import ConfigCenter from './components/config/ConfigCenter.vue'
import ProjectDialog from './components/ProjectDialog.vue'
import { useWorkspace } from './composables/useWorkspace'
import { api } from './api/client'
import type { Project } from './types'

const workspace = useWorkspace()
const composer = ref<InstanceType<typeof PromptComposer> | null>(null)
const showConfiguration = ref(false)
const showProjectDialog = ref(false)
const leftPanelOpen = ref(true)
const rightPanelOpen = ref(true)

// DAG and timeline panel visibility
const showDagPanel = ref(true)
const showTimelinePanel = ref(true)

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

const subtitle = computed(() => {
  const run = workspace.state.activeRun
  if (!run) return '描述目标，主调度器会生成任务 DAG 并调用专业 Agent。'
  const labels = { queued: '等待执行', running: '正在执行', completed: '执行完成', failed: '执行失败', cancelled: '已取消' }
  return labels[run.status]
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
      @toggle-left="leftPanelOpen = !leftPanelOpen"
      @toggle-right="rightPanelOpen = !rightPanelOpen"
      @configure="showConfiguration = true"
      @switch-project="showProjectDialog = true"
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
        <strong>连接出现问题</strong>
        <span>{{ workspace.state.error }}</span>
      </div>

      <!-- No project selected -->
      <template v-if="!currentProject">
        <section class="welcome-panel">
          <div class="welcome-symbol">&#x1F4E6;</div>
          <h2>欢迎使用 Agent Studio</h2>
          <p>选择一个项目开始，或创建新项目来配置 Agent 团队。</p>
          <div class="suggestion-grid">
            <button type="button" @click="showProjectDialog = true">创建或选择项目</button>
          </div>
        </section>
      </template>

      <!-- Has project -->
      <template v-else>
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

          <!-- 历史对话 -->
          <StreamingChat
            :turns="workspace.state.conversationTurns"
            :streaming="workspace.state.streamingState"
            :active-run-id="null"
            :is-running="false"
            @fork="forkRun"
          />

          <section class="welcome-panel" style="min-height:120px">
            <div class="suggestion-grid">
              <button type="button" @click="submit('分析当前项目，并制定前后端下一阶段的实现计划')">分析项目并制定计划</button>
              <button type="button" @click="submit('检查当前代码质量，分别执行前端和后端审查')">并行审查前后端代码</button>
            </div>
          </section>
        </template>

        <!-- 有活跃运行：流式对话 + 面板 -->
        <template v-else>
          <div class="run-status-bar">
            <span class="eyebrow">
              正在执行: {{ workspace.state.activeRun.objective.slice(0, 60) }}{{ workspace.state.activeRun.objective.length > 60 ? '…' : '' }}
            </span>
            <button class="stop-button" type="button" @click="workspace.cancelActiveRun()">
              <span aria-hidden="true">&#x25A0;</span> 停止任务
            </button>
          </div>

          <!-- 主对话区域 -->
          <StreamingChat
            :turns="workspace.state.conversationTurns"
            :streaming="workspace.state.streamingState"
            :active-run-id="workspace.state.activeRun?.id ?? null"
            :is-running="workspace.isRunning.value"
            @fork="forkRun"
          />

          <!-- 面板切换栏 -->
          <div class="panel-toggle-bar">
            <button
              type="button"
              class="panel-toggle-btn"
              :class="{ active: showDagPanel }"
              @click="showDagPanel = !showDagPanel"
            >
              <span aria-hidden="true">{{ showDagPanel ? '⌃' : '⌄' }}</span>
              任务流程图
              <span class="panel-toggle-badge">{{ workspace.plan.value.length }} 节点</span>
            </button>
            <button
              type="button"
              class="panel-toggle-btn"
              :class="{ active: showTimelinePanel }"
              @click="showTimelinePanel = !showTimelinePanel"
            >
              <span aria-hidden="true">{{ showTimelinePanel ? '⌃' : '⌄' }}</span>
              思考流程
              <span class="panel-toggle-badge">{{ workspace.state.events.length }} 事件</span>
            </button>
          </div>

          <!-- DAG 图面板 -->
          <div v-if="showDagPanel" class="dag-panel-wrapper">
            <DagGraph
              :tasks="workspace.plan.value"
              :contract="workspace.planContract.value"
              :events="workspace.state.events"
              :turns="workspace.state.conversationTurns"
              :memory-compactions="workspace.state.memoryCompactions"
            />
          </div>

          <!-- 思考流程面板 -->
          <div v-if="showTimelinePanel" class="timeline-panel-wrapper">
            <ThinkingTimeline
              :key="workspace.state.activeRun?.id"
              :tasks="workspace.plan.value"
              :events="workspace.state.events"
              :turns="workspace.state.conversationTurns"
              :memory-compactions="workspace.state.memoryCompactions"
            />
          </div>

          <!-- 最终汇总 -->
          <section v-if="workspace.state.activeRun.final_answer && !showTimelinePanel" class="final-answer">
            <span class="eyebrow">最终汇总</span>
            <pre>{{ workspace.state.activeRun.final_answer }}</pre>
          </section>
        </template>

        <!-- 底部输入框始终存在 -->
        <PromptComposer
          ref="composer"
          :submitting="workspace.state.submitting"
          :is-running="workspace.isRunning.value"
          :queue-items="workspace.state.taskQueue"
          :active-agents="workspace.state.activeAgents"
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

    <AgentInspector
      :agents="workspace.state.agents"
      :events="workspace.state.events"
      :deepseek-balance="workspace.state.deepseekBalance"
      :deepseek-usage="workspace.state.deepseekUsage"
      :balance-loading="workspace.state.balanceLoading"
      :project-id="currentProject?.id || ''"
      @refresh-balance="workspace.refreshDeepSeekBalance(true)"
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
  </div>
</template>

<style scoped>
/* Run status bar */
.run-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: var(--content-width);
  margin: 0 auto 0.5rem;
  width: 100%;
}

/* Panel toggle bar */
.panel-toggle-bar {
  display: flex;
  gap: 0.5rem;
  max-width: var(--content-width);
  margin: 0.75rem auto 0;
  width: 100%;
}

.panel-toggle-btn {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  border: 0;
  border-radius: 8px;
  padding: 0.45rem 0.75rem;
  background: var(--surface);
  color: var(--secondary);
  cursor: pointer;
  font-size: 0.65rem;
  font-weight: 550;
  border: 1px solid var(--separator-soft);
  transition: background 0.15s, color 0.15s;
}

.panel-toggle-btn:hover {
  background: var(--surface-hover);
  color: var(--label);
}

.panel-toggle-btn.active {
  background: var(--blue-soft);
  color: #64d2ff;
  border-color: rgba(10, 132, 255, 0.25);
}

.panel-toggle-badge {
  font-size: 0.55rem;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  background: rgba(118, 118, 128, 0.18);
}

.panel-toggle-btn.active .panel-toggle-badge {
  background: rgba(10, 132, 255, 0.18);
}

/* Panel wrappers */
.dag-panel-wrapper,
.timeline-panel-wrapper {
  max-width: var(--content-width);
  margin: 0.5rem auto 0;
  width: 100%;
}

/* Adjust workspace padding: less bottom padding since chat fills the space */
.workspace {
  padding-bottom: 175px;
}
</style>
