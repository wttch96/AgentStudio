<script setup lang="ts">
import { ref } from 'vue'
import type { AgentProfile, SkillProfile } from '../../types'
import AgentConfigEditor from './AgentConfigEditor.vue'
import BrainConfigEditor from './BrainConfigEditor.vue'
import SchedulerConfigEditor from './SchedulerConfigEditor.vue'
import SkillConfigEditor from './SkillConfigEditor.vue'
import WorkspaceConfigEditor from './WorkspaceConfigEditor.vue'
import MemoryConfigEditor from './MemoryConfig.vue'
import RAGConfigEditor from './RAGConfigEditor.vue'
import KnowledgeConfig from './KnowledgeConfig.vue'

defineProps<{ agents: AgentProfile[]; skills: SkillProfile[]; projectId: string }>()
defineEmits<{ close: []; saved: [] }>()
const tab = ref<'brain' | 'rag' | 'knowledge' | 'agents' | 'skills' | 'workspace' | 'scheduler' | 'memory'>('brain')
</script>

<template>
  <div class="config-backdrop" @click.self="$emit('close')">
    <section class="config-center" role="dialog" aria-modal="true" aria-label="Agent Studio 配置中心">
      <header class="config-header">
        <div>
          <span class="eyebrow">本机配置</span>
          <h2>Agent Studio 配置</h2>
        </div>
        <ElButton text circle aria-label="关闭配置中心" @click="$emit('close')">×</ElButton>
      </header>
      <ElTabs v-model="tab" class="config-tabs">
        <ElTabPane label="主脑配置" name="brain" />
        <ElTabPane label="RAG 配置" name="rag" />
        <ElTabPane label="知识库" name="knowledge" />
        <ElTabPane label="Agent 配置" name="agents" />
        <ElTabPane label="Skill 编辑" name="skills" />
        <ElTabPane label="工作目录" name="workspace" />
        <ElTabPane label="调度配置" name="scheduler" />
        <ElTabPane label="记忆配置" name="memory" />
      </ElTabs>
      <BrainConfigEditor v-if="tab === 'brain'" @saved="$emit('saved')" />
      <RAGConfigEditor v-else-if="tab === 'rag'" :agents="agents" :project-id="projectId" @saved="$emit('saved')" />
      <KnowledgeConfig v-else-if="tab === 'knowledge'" :project-id="projectId" />
      <AgentConfigEditor v-else-if="tab === 'agents'" :agents="agents" :skills="skills" :project-id="projectId" @saved="$emit('saved')" />
      <SkillConfigEditor v-else-if="tab === 'skills'" :skills="skills" :project-id="projectId" @saved="$emit('saved')" />
      <WorkspaceConfigEditor v-else-if="tab === 'workspace'" @saved="$emit('saved')" />
      <SchedulerConfigEditor v-else-if="tab === 'scheduler'" @saved="$emit('saved')" />
      <MemoryConfigEditor v-else-if="tab === 'memory'" @saved="$emit('saved')" />

    </section>
  </div>
</template>
