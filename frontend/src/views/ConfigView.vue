<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import AgentConfigEditor from '../components/config/AgentConfigEditor.vue'
import BrainConfigEditor from '../components/config/BrainConfigEditor.vue'
import SchedulerConfigEditor from '../components/config/SchedulerConfigEditor.vue'
import SkillConfigEditor from '../components/config/SkillConfigEditor.vue'
import WorkspaceConfigEditor from '../components/config/WorkspaceConfigEditor.vue'
import MemoryConfigEditor from '../components/config/MemoryConfig.vue'
import RAGConfigEditor from '../components/config/RAGConfigEditor.vue'
import KnowledgeConfig from '../components/config/KnowledgeConfig.vue'
import { useWorkspace } from '../composables/useWorkspace'
import { api } from '../api/client'
import type { AgentProfile, Project, SkillProfile } from '../types'

const route = useRoute()
const workspace = useWorkspace()

const tab = ref<'brain' | 'rag' | 'knowledge' | 'agents' | 'skills' | 'workspace' | 'scheduler' | 'memory'>('agents')
const agents = ref<AgentProfile[]>([])
const skills = ref<SkillProfile[]>([])
const projects = ref<Project[]>([])
const projectId = ref('')
const loading = ref(true)

const tabs = [
  { key: 'agents' as const, label: 'Agent 配置', icon: '🤖' },
  { key: 'skills' as const, label: 'Skill 编辑', icon: '🔧' },
  { key: 'brain' as const, label: '主脑配置', icon: '🧠' },
  { key: 'rag' as const, label: 'RAG 配置', icon: '📚' },
  { key: 'knowledge' as const, label: '知识库', icon: '📖' },
  { key: 'workspace' as const, label: '工作目录', icon: '📁' },
  { key: 'scheduler' as const, label: '调度配置', icon: '⚙️' },
  { key: 'memory' as const, label: '记忆配置', icon: '💾' },
]

async function loadData() {
  loading.value = true
  try {
    const [projList, agentList, skillList] = await Promise.all([
      api.projects(),
      api.agents(projectId.value || undefined),
      api.skills(projectId.value || undefined),
    ])
    projects.value = projList.items
    agents.value = agentList
    skills.value = skillList
    if (projList.items.length > 0 && !projectId.value) {
      projectId.value = projList.items[0].id
    }
  } catch { /* */ }
  loading.value = false
}

async function onSaved() {
  await loadData()
}

watch(() => route.query.tab, (t) => {
  if (t && tabs.some(tb => tb.key === t)) tab.value = t as typeof tab.value
})

onMounted(loadData)
</script>

<template>
  <ElContainer class="h-100">
    <!-- Left sidebar -->
    <ElAside width="260px" class="config-aside">
      <div class="p-3 border-bottom">
        <h6 class="text-secondary">配置中心</h6>
      </div>
      <div class="p-2 border-bottom">
        <ElSelect v-model="projectId" size="small" @change="loadData" clearable class="w-100" placeholder="选择项目">
          <ElOption value="" label="-- 选择项目 --" />
          <ElOption v-for="p in projects" :key="p.id" :value="p.id" :label="p.name" />
        </ElSelect>
      </div>
      <ElMenu :default-active="tab" class="config-nav" @select="(key: string) => tab = key as any">
        <ElMenuItem v-for="t in tabs" :key="t.key" :index="t.key">
          <span class="me-2">{{ t.icon }}</span>{{ t.label }}
        </ElMenuItem>
      </ElMenu>
    </ElAside>

    <!-- Main content -->
    <ElMain class="config-main">
      <div v-if="loading" class="d-flex align-items-center gap-2 text-secondary p-4">
        <ElIcon class="is-loading"><Loading /></ElIcon> 加载中&hellip;
      </div>

      <template v-else>
        <BrainConfigEditor v-if="tab === 'brain'" @saved="onSaved" />
        <RAGConfigEditor v-else-if="tab === 'rag'" :agents="agents" :project-id="projectId" @saved="onSaved" />
        <KnowledgeConfig v-else-if="tab === 'knowledge'" :project-id="projectId" />
        <AgentConfigEditor v-else-if="tab === 'agents'" :agents="agents" :skills="skills" :project-id="projectId" @saved="onSaved" />
        <SkillConfigEditor v-else-if="tab === 'skills'" :skills="skills" :project-id="projectId" @saved="onSaved" />
        <WorkspaceConfigEditor v-else-if="tab === 'workspace'" @saved="onSaved" />
        <SchedulerConfigEditor v-else-if="tab === 'scheduler'" @saved="onSaved" />
        <MemoryConfigEditor v-else-if="tab === 'memory'" @saved="onSaved" />
      </template>
    </ElMain>
  </ElContainer>
</template>

<style scoped>
.config-aside {
  border-right: 1px solid var(--el-border-color-light);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.config-nav {
  border-right: none;
  flex: 1;
}
.config-nav .el-menu-item {
  padding-left: 20px !important;
}
.config-main {
  overflow-y: auto;
  padding: 24px;
}
.text-secondary {
  color: var(--el-text-color-secondary);
}
</style>
