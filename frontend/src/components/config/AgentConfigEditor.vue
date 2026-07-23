<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../../api/client'
import type { AgentDetail, AgentProfile, SkillProfile, AgentTemplate } from '../../types'

const props = defineProps<{ agents: AgentProfile[]; skills: SkillProfile[]; projectId: string }>()
const emit = defineEmits<{ saved: [] }>()
const knownTools = ['Read', 'Glob', 'Grep', 'Write', 'Edit', 'Bash', 'Skill']
const selectedName = ref('__new__')
const saving = ref(false)
const message = ref('')
const form = reactive<AgentDetail & { id: string; sub_dir: string; display_name: string; agent_type: string }>({
  id: '', name: '', display_name: '', description: '', tools: [], skills: [],
  skill_count: 0, builtin: false, prompt: '', sub_dir: '', agent_type: 'claude',
})

// Template list for new agent creation
const templates = ref<AgentTemplate[]>([])
const newTemplateId = ref('')
const newName = ref('')
const showNewForm = ref(false)
const deleting = ref(false)

const codingAgents = ref<AgentProfile[]>([])
watch(() => props.agents, (agents) => {
  codingAgents.value = agents.filter(a => a.agent_type !== 'brain' && a.agent_type !== 'rag')
  if (!selectedName.value && codingAgents.value[0]) {
    selectedName.value = codingAgents.value[0].name
  }
}, { immediate: true })

function reset() {
  Object.assign(form, { id: '', name: '', display_name: '', description: '', tools: [], skills: [],
    skill_count: 0, builtin: false, prompt: '', sub_dir: '', agent_type: 'claude' })
  message.value = ''
}

function agentTypeLabel(t: string) {
  return t === 'claude' ? 'Claude Agent (SDK)' : t === 'rag' ? 'RAG Agent' : t === 'deepseek' ? 'DeepSeek Agent (LangChain)' : 'Agent'
}

async function select(name: string) {
  selectedName.value = name
  if (name === '__new__') {
    reset()
    showNewForm.value = true
    try { templates.value = (await api.templates()).items.filter(t => t.agent_type !== 'brain') } catch { templates.value = [] }
    return
  }
  showNewForm.value = false
  if (!props.projectId) return
  message.value = ''
  try {
    const detail = await api.agent(name, props.projectId)
    Object.assign(form, detail)
    const agent = codingAgents.value.find(a => a.name === name)
    if (agent?.id) { form.id = agent.id; form.agent_type = agent.agent_type || 'claude' }
  } catch (error) {
    message.value = error instanceof Error ? error.message : '读取 Agent 失败'
  }
}

function toggle(list: string[], value: string) {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

async function createNew() {
  if (!props.projectId || !newTemplateId.value) {
    message.value = '请选择 Agent 模板'
    return
  }
  saving.value = true; message.value = ''
  try {
    const tmpl = templates.value.find(t => t.id === newTemplateId.value)
    await api.addProjectAgent(props.projectId, newTemplateId.value)
    message.value = 'Agent 已创建'
    emit('saved')
    showNewForm.value = false
    selectedName.value = '__new__'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '创建失败'
  } finally { saving.value = false }
}

async function save() {
  if (!props.projectId || !form.id) {
    message.value = '请先选择或创建一个 Agent'
    return
  }
  saving.value = true; message.value = ''
  try {
    const payload: Record<string, unknown> = {
      display_name: form.display_name,
      description: form.description,
      system_prompt: form.prompt,
      skills: form.skills,
    }
    // Claude agent: save tools and sub_dir
    if (form.agent_type === 'claude') {
      payload.tools = form.tools
      payload.sub_dir = form.sub_dir
    }
    await api.updateProjectAgent(props.projectId, form.id, payload)
    message.value = 'Agent 配置已保存'
    emit('saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally { saving.value = false }
}

async function deleteAgent() {
  if (!props.projectId || !form.id) return
  if (!confirm(`确定删除 Agent "${form.display_name || form.name}"？此操作不可恢复。`)) return
  deleting.value = true; message.value = ''
  try {
    await api.deleteProjectAgent(props.projectId, form.id)
    reset()
    selectedName.value = codingAgents.value[0]?.name || '__new__'
    message.value = 'Agent 已删除'
    emit('saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '删除失败'
  } finally { deleting.value = false }
}

watch(selectedName, select, { immediate: true })
watch(() => props.projectId, (pid) => { if (pid && selectedName.value && selectedName.value !== '__new__') select(selectedName.value) })
</script>

<template>
  <div class="config-editor">
    <div v-if="!projectId" class="config-empty">
      请先在顶部选择一个项目，然后在这里配置 Agent。
    </div>
    <template v-else>
      <!-- Agent selector -->
      <label class="field-label">Agent 列表</label>
      <div class="config-selector">
        <button type="button" :class="{ active: selectedName === '__new__' }" @click="select('__new__')">＋ 新增</button>
        <button
          v-for="agent in codingAgents"
          :key="agent.name"
          type="button"
          :class="{ active: selectedName === agent.name }"
          @click="select(agent.name)"
        >
          {{ agent.display_name || agent.name }}
          <small>{{ agentTypeLabel(agent.agent_type || 'claude') }} · {{ agent.skill_count }} Skill</small>
        </button>
      </div>

      <!-- New Agent creation form -->
      <template v-if="showNewForm">
        <label class="field-label">从模板创建新 Agent</label>
        <select v-model="newTemplateId" class="config-input">
          <option value="">-- 选择模板 --</option>
          <option v-for="t in templates" :key="t.id" :value="t.id">
            {{ t.display_name }} ({{ agentTypeLabel(t.agent_type) }})
          </option>
        </select>
        <div class="config-actions">
          <span :class="{ error: message.includes('失败') }">{{ message }}</span>
          <button type="button" :disabled="saving" @click="createNew">{{ saving ? '创建中…' : '创建 Agent' }}</button>
        </div>
      </template>

      <!-- Edit form (only when an existing agent is selected) -->
      <template v-else-if="selectedName !== '__new__'">
        <label class="field-label">
          {{ agentTypeLabel(form.agent_type) }}
        </label>

        <label class="field-label" for="agent-display-name">显示名称</label>
        <input id="agent-display-name" v-model="form.display_name" class="config-input" />

        <label class="field-label" for="agent-description">用途说明</label>
        <input id="agent-description" v-model="form.description" class="config-input" />

        <!-- Claude-only: working directory -->
        <template v-if="form.agent_type === 'claude'">
          <label class="field-label" for="agent-subdir">工作子目录</label>
          <input id="agent-subdir" v-model="form.sub_dir" class="config-input" placeholder="例如 frontend / backend" />
        </template>

        <!-- Claude-only: tools -->
        <template v-if="form.agent_type === 'claude'">
          <span class="field-label">预批准工具</span>
          <div class="choice-grid">
            <label v-for="tool in knownTools" :key="tool">
              <input type="checkbox" :checked="form.tools.includes(tool)" @change="toggle(form.tools, tool)" />
              {{ tool }}
            </label>
          </div>
        </template>

        <!-- All agent types: skills -->
        <span class="field-label">关联 Skill（{{ form.skills.length }}）</span>
        <div v-if="skills.length" class="choice-grid skill-choices">
          <label v-for="skill in skills" :key="skill.name" :title="skill.description">
            <input
              type="checkbox"
              :checked="form.skills.includes(skill.name)"
              @change="toggle(form.skills, skill.name)"
            />
            {{ skill.name }}
          </label>
        </div>
        <p v-else class="config-empty">还没有 Skill，请先在「Skill 编辑」中创建。</p>

        <!-- All agent types: prompt -->
        <label class="field-label" for="agent-prompt">系统提示词</label>
        <textarea id="agent-prompt" v-model="form.prompt" class="config-textarea" rows="12" />

        <!-- Actions -->
        <div class="config-actions">
          <span :class="{ error: message.includes('失败') || message.includes('删除') }">{{ message }}</span>
          <button type="button" class="danger" :disabled="deleting" @click="deleteAgent">{{ deleting ? '删除中…' : '删除 Agent' }}</button>
          <button type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存 Agent' }}</button>
        </div>
      </template>
    </template>
  </div>
</template>
