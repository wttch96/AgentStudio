<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../../api/client'
import type { AgentProfile } from '../../types'

const props = defineProps<{ agents: AgentProfile[]; projectId: string }>()
const emit = defineEmits<{ saved: [] }>()
const selectedName = ref('')
const saving = ref(false)
const message = ref('')
const form = reactive({ id: '', name: '', display_name: '', description: '', prompt: '', sub_dir: '' })

// Filter to only RAG agents
const ragAgents = ref<AgentProfile[]>([])
watch(() => props.agents, (agents) => {
  ragAgents.value = agents.filter(a => a.agent_type === 'rag')
  if (!selectedName.value && ragAgents.value[0]) {
    selectedName.value = ragAgents.value[0].name
  }
}, { immediate: true })

async function load(name: string) {
  if (!name || !props.projectId) return
  message.value = ''
  try {
    const detail = await api.agent(name, props.projectId)
    Object.assign(form, detail)
    const agent = ragAgents.value.find(a => a.name === name)
    if (agent?.id) form.id = agent.id
  } catch (error) {
    message.value = error instanceof Error ? error.message : '读取 Agent 失败'
  }
}

async function save() {
  if (!props.projectId || !form.id) {
    message.value = '请先在项目管理中创建 RAG Agent'
    return
  }
  saving.value = true; message.value = ''
  try {
    await api.updateProjectAgent(props.projectId, form.id, {
      display_name: form.display_name,
      description: form.description,
      system_prompt: form.prompt,
    })
    message.value = 'RAG Agent 配置已保存'
    emit('saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally { saving.value = false }
}

watch(selectedName, load, { immediate: true })
watch(() => props.projectId, (pid) => { if (pid && selectedName.value) load(selectedName.value) })
</script>

<template>
  <div class="config-editor">
    <div v-if="!projectId" class="config-empty">
      请先在顶部选择一个项目
    </div>
    <template v-else>
      <label class="field-label">RAG Agent (LangChain + DeepSeek)</label>
      <div v-if="!ragAgents.length" class="config-empty">
        还没有 RAG Agent，请通过顶部「项目管理」为当前项目添加知识库 RAG 模板。
      </div>
      <div v-else class="config-selector">
        <button
          v-for="agent in ragAgents"
          :key="agent.name"
          type="button"
          :class="{ active: selectedName === agent.name }"
          @click="selectedName = agent.name"
        >
          {{ agent.display_name || agent.name }}
        </button>
      </div>

      <label class="field-label" for="rag-description">用途说明</label>
      <input id="rag-description" v-model="form.description" class="config-input" />

      <label class="field-label" for="rag-prompt">RAG Agent 系统提示词</label>
      <textarea id="rag-prompt" v-model="form.prompt" class="config-textarea" rows="12"
        placeholder="定义 RAG Agent 的知识检索策略、综合规则和输出格式..." />

      <div class="config-actions">
        <span :class="{ error: message.includes('失败') }">{{ message }}</span>
        <button type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存 RAG Agent' }}</button>
      </div>
    </template>
  </div>
</template>
