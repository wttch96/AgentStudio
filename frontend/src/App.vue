<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AgentInspector from './components/AgentInspector.vue'
import AppHeader from './components/AppHeader.vue'
import EventTimeline from './components/EventTimeline.vue'
import DagGraph from './components/DagGraph.vue'
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

// Project state
const projects = ref<Project[]>([])
const currentProject = ref<Project | null>(null)

async function loadProjects() {
  try { projects.value = (await api.projects()).items } catch { /* */ }
}

function selectProject(p: Project) {
  currentProject.value = p
  showProjectDialog.value = false
  workspace.refreshConfiguration()
}

function onProjectCreated(p: Project) {
  projects.value.unshift(p)
  currentProject.value = p
  showProjectDialog.value = false
  workspace.refreshConfiguration()
}

watch(currentProject, (p) => {
  if (p) {
    workspace.state.projectId = p.id
    workspace.state.projectName = p.name
  }
})

const isContinuation = computed(() => {
  const run = workspace.state.activeRun
  return Boolean(run && ['completed', 'failed', 'cancelled'].includes(run.status))
})
const upstreamRun = computed(() => {
  const parentId = workspace.state.activeRun?.parent_run_id
  return parentId ? workspace.state.runs.find((run) => run.id === parentId) ?? null : null
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

async function retryTask(taskId: string) {
  await workspace.createRun('/retry ' + taskId)
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

        <template v-if="workspace.state.activeRun">
          <section v-if="upstreamRun" class="continuation-context">
            <span class="continuation-link" aria-hidden="true">&#x21B3;</span>
            <div>
              <span>正在延续第 {{ upstreamRun.turn_index }} 轮</span>
              <strong>{{ upstreamRun.objective }}</strong>
            </div>
            <button type="button" @click="workspace.selectRun(upstreamRun.id)">查看上游</button>
          </section>

          <DagGraph
            :tasks="workspace.plan.value"
            :contract="workspace.planContract.value"
            :events="workspace.state.events"
          />
          <EventTimeline
            :key="workspace.state.activeRun.id"
            :tasks="workspace.plan.value"
            :events="workspace.state.events"
          />
          <section v-if="workspace.state.activeRun.final_answer" class="final-answer">
            <span class="eyebrow">最终汇总</span>
            <pre>{{ workspace.state.activeRun.final_answer }}</pre>
          </section>
        </template>

        <template v-else>
          <div class="workspace-heading">
            <div>
              <span class="eyebrow">{{ currentProject.name }}</span>
              <h1>今天想让 Agent 团队完成什么？</h1>
              <p>{{ subtitle }}</p>
            </div>
            <button
              v-if="workspace.isRunning.value"
              class="stop-button"
              type="button"
              @click="workspace.cancelActiveRun"
            >
              <span aria-hidden="true">&#x25A0;</span> 停止
            </button>
          </div>

          <section class="welcome-panel" style="min-height:200px">
            <div class="suggestion-grid">
              <button type="button" @click="submit('分析当前项目，并制定前后端下一阶段的实现计划')">分析项目并制定计划</button>
              <button type="button" @click="submit('检查当前代码质量，分别执行前端和后端审查')">并行审查前后端代码</button>
            </div>
          </section>
        </template>

        <PromptComposer
          ref="composer"
          :submitting="workspace.state.submitting"
          :continuing="isContinuation"
          :disabled="workspace.isRunning.value"
          @submit="submit"
        />
      </template>
    </main>

    <AgentInspector
      :agents="workspace.state.agents"
      :events="workspace.state.events"
      :deepseek-balance="workspace.state.deepseekBalance"
      :deepseek-usage="workspace.state.deepseekUsage"
      :balance-loading="workspace.state.balanceLoading"
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
