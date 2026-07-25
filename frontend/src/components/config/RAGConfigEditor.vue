<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { Collection } from '@element-plus/icons-vue'
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
  <div class="d-flex flex-column gap-3">
    <ElAlert v-if="!projectId" type="info" :closable="false">
      请先在顶部选择一个项目
    </ElAlert>

    <template v-else>
      <div>
        <label class="form-label">RAG Agent (LangChain + DeepSeek)</label>
        <div v-if="!ragAgents.length" class="text-secondary small py-3">
          还没有 RAG Agent，请通过顶部「项目管理」为当前项目添加知识库 RAG 模板。
        </div>
        <div v-else class="d-flex flex-wrap gap-1">
          <ElButton
            v-for="agent in ragAgents"
            :key="agent.name"
            size="small"
            :type="selectedName === agent.name ? 'primary' : ''"
            @click="selectedName = agent.name"
          >
            {{ agent.display_name || agent.name }}
          </ElButton>
        </div>
      </div>

      <ElCard v-if="ragAgents.length">
        <template #header>
          <div class="d-flex align-items-center gap-2">
            <ElIcon size="20"><Collection /></ElIcon>
            <span><strong>{{ form.display_name || form.name || 'RAG Agent' }}</strong></span>
          </div>
        </template>

        <div class="mb-3">
          <label class="form-label" for="rag-description">用途说明</label>
          <ElInput id="rag-description" v-model="form.description" size="small" />
        </div>

        <div class="mb-3">
          <label class="form-label" for="rag-prompt">RAG Agent 系统提示词</label>
          <ElInput id="rag-prompt" v-model="form.prompt" type="textarea" size="small" :rows="12"
            placeholder="定义 RAG Agent 的知识检索策略、综合规则和输出格式..." />
        </div>

        <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" :closable="false" class="mb-3">{{ message }}</ElAlert>
        <ElButton type="primary" size="small" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存 RAG Agent' }}</ElButton>
      </ElCard>
    </template>
  </div>
</template>
