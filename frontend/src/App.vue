<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AgentInspector from './components/AgentInspector.vue'
import AppHeader from './components/AppHeader.vue'
import EventTimeline from './components/EventTimeline.vue'
import PlanBoard from './components/PlanBoard.vue'
import PromptComposer from './components/PromptComposer.vue'
import RunSidebar from './components/RunSidebar.vue'
import ConfigCenter from './components/config/ConfigCenter.vue'
import { useWorkspace } from './composables/useWorkspace'

const workspace = useWorkspace()
const composer = ref<InstanceType<typeof PromptComposer> | null>(null)
const showConfiguration = ref(false)
const leftPanelOpen = ref(true)
const rightPanelOpen = ref(true)
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
  await workspace.createRun(`/retry ${taskId}`)
}

function newRun() {
  workspace.beginNewRun()
  void composer.value?.focus()
}

async function configurationSaved() {
  await workspace.refreshConfiguration()
}

onMounted(workspace.initialize)
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
      @toggle-left="leftPanelOpen = !leftPanelOpen"
      @toggle-right="rightPanelOpen = !rightPanelOpen"
      @configure="showConfiguration = true"
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

      <div class="workspace-heading">
        <div>
          <span class="eyebrow">Agent 工作台</span>
          <h1>{{ workspace.state.activeRun?.objective ?? '今天想让 Agent 团队完成什么？' }}</h1>
          <p>{{ subtitle }}</p>
        </div>
        <button
          v-if="workspace.isRunning.value"
          class="stop-button"
          type="button"
          @click="workspace.cancelActiveRun"
        >
          <span aria-hidden="true">■</span> 停止
        </button>
      </div>

      <div v-if="workspace.state.loading" class="loading-state">
        <span class="loading-orb" /> 正在连接本地调度器…
      </div>

      <template v-else-if="workspace.state.activeRun">
        <section v-if="upstreamRun" class="continuation-context">
          <span class="continuation-link" aria-hidden="true">↳</span>
          <div>
            <span>正在延续第 {{ upstreamRun.turn_index }} 轮</span>
            <strong>{{ upstreamRun.objective }}</strong>
          </div>
          <button type="button" @click="workspace.selectRun(upstreamRun.id)">查看上游</button>
        </section>
        <PlanBoard
          :tasks="workspace.plan.value"
          :events="workspace.state.events"
          :can-retry="!workspace.isRunning.value"
          @retry="retryTask"
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

      <section v-else class="welcome-panel">
        <div class="welcome-symbol">⌘</div>
        <h2>一个目标，多个专业执行者</h2>
        <p>DeepSeek 负责拆解与决策，LangGraph 负责执行任务图，Claude Agent 自主使用工具完成节点。</p>
        <div class="suggestion-grid">
          <button type="button" @click="submit('分析当前项目，并制定前后端下一阶段的实现计划')">分析项目并制定计划</button>
          <button type="button" @click="submit('检查当前代码质量，分别执行前端和后端审查')">并行审查前后端代码</button>
        </div>
      </section>

      <PromptComposer
        ref="composer"
        :submitting="workspace.state.submitting"
        :continuing="isContinuation"
        :disabled="workspace.isRunning.value"
        @submit="submit"
      />
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
      @close="showConfiguration = false"
      @saved="configurationSaved"
    />
  </div>
</template>
