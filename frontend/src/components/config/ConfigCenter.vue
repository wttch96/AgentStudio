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

defineProps<{ agents: AgentProfile[]; skills: SkillProfile[]; projectId: string }>()
defineEmits<{ close: []; saved: [] }>()
const tab = ref<'brain' | 'rag' | 'agents' | 'skills' | 'workspace' | 'scheduler' | 'memory'>('brain')
</script>

<template>
  <div class="config-backdrop" @click.self="$emit('close')">
    <section class="config-center" role="dialog" aria-modal="true" aria-label="Agent Studio 配置中心">
      <header class="config-header">
        <div>
          <span class="eyebrow">本机配置</span>
          <h2>Agent Studio 配置</h2>
        </div>
        <button type="button" aria-label="关闭配置中心" @click="$emit('close')">×</button>
      </header>
      <nav class="config-tabs" aria-label="配置类型">
<button type="button" :class="{ active: tab === 'brain' }" @click="tab = 'brain'">主脑配置</button>
        <button type="button" :class="{ active: tab === 'rag' }" @click="tab = 'rag'">RAG 配置</button>
        <button type="button" :class="{ active: tab === 'agents' }" @click="tab = 'agents'">Agent 配置</button>
        <button type="button" :class="{ active: tab === 'skills' }" @click="tab = 'skills'">Skill 编辑</button>
        <button type="button" :class="{ active: tab === 'workspace' }" @click="tab = 'workspace'">工作目录</button>
        <button type="button" :class="{ active: tab === 'scheduler' }" @click="tab = 'scheduler'">调度配置</button>
        <button type="button" :class="{ active: tab === 'memory' }" @click="tab = 'memory'">记忆配置</button>
      </nav>
      <BrainConfigEditor v-if="tab === 'brain'" @saved="$emit('saved')" />
      <RAGConfigEditor v-else-if="tab === 'rag'" :agents="agents" :project-id="projectId" @saved="$emit('saved')" />
      <AgentConfigEditor v-else-if="tab === 'agents'" :agents="agents" :skills="skills" :project-id="projectId" @saved="$emit('saved')" />
      <SkillConfigEditor v-else-if="tab === 'skills'" :skills="skills" :project-id="projectId" @saved="$emit('saved')" />
      <WorkspaceConfigEditor v-else-if="tab === 'workspace'" @saved="$emit('saved')" />
      <SchedulerConfigEditor v-else-if="tab === 'scheduler'" @saved="$emit('saved')" />
      <MemoryConfigEditor v-else-if="tab === 'memory'" @saved="$emit('saved')" />

    </section>
  </div>
</template>
