<script setup lang="ts">
import { reactive, ref, watch, type Ref } from 'vue'
import { Plus, UserFilled } from '@element-plus/icons-vue'
import { api } from '../../api/client'
import type { AgentDetail, AgentProfile, SkillProfile, AgentTemplate } from '../../types'

const props = defineProps<{ agents: AgentProfile[]; skills: SkillProfile[]; projectId: string }>()
const emit = defineEmits<{ saved: [] }>()
const selectedName = ref('__new__')
const saving = ref(false)
const message = ref('')
const form = reactive<AgentDetail & { id: string; sub_dir: string; display_name: string; agent_type: string }>({
  id: '', name: '', display_name: '', description: '', skills: [],
  skill_count: 0, builtin: false, prompt: '', sub_dir: '', agent_type: 'claude', model: '',
  role: 'implementation_agent', capabilities: [], limitations: [], preferred_tasks: [],
  forbidden_tasks: [], input_contract: {}, output_contract: {}, dependencies_info: [],
  priority: 0, max_iterations: 3,
})

const templates = ref<AgentTemplate[]>([])
const newTemplateId = ref('')
const showNewForm = ref(true)
const createMode = ref<'template' | 'manual'>('template')
const deleting = ref(false)
const manualName = ref('')
const manualDisplayName = ref('')
const manualAgentType = ref('rag')
const manualSubDir = ref('')
const manualPrompt = ref('')
const manualModel = ref('')
const manualDescription = ref('')
const manualSkills: Ref<string[]> = ref([])

const codingAgents = ref<AgentProfile[]>([])
watch(() => props.agents, (agents) => {
  codingAgents.value = agents
  if (codingAgents.value.length > 0 && selectedName.value === '__new__') {
    selectedName.value = codingAgents.value[0].name
  }
}, { immediate: true })

function reset() {
  Object.assign(form, { id: '', name: '', display_name: '', description: '', skills: [],
    skill_count: 0, builtin: false, prompt: '', sub_dir: '', agent_type: 'claude', model: '' })
  Object.assign(form, {
    role: 'implementation_agent', capabilities: [], limitations: [], preferred_tasks: [],
    forbidden_tasks: [], input_contract: {}, output_contract: {}, dependencies_info: [],
    priority: 0, max_iterations: 3,
  })
  message.value = ''
}
function resetManualForm() {
  manualName.value = ''; manualDisplayName.value = ''; manualAgentType.value = 'rag'
  manualSubDir.value = ''; manualPrompt.value = ''; manualModel.value = ''
  manualDescription.value = ''; manualSkills.value = []
}
function agentTypeLabel(t: string) {
  return t === 'claude' ? 'Claude Agent (SDK)' : t === 'rag' ? 'RAG Agent' : t === 'chat' ? 'Chat Agent' : t === 'file-ops' ? '文件操作 Agent' : 'Agent'
}

async function select(name: string) {
  selectedName.value = name
  if (name === '__new__') {
    reset(); showNewForm.value = true; createMode.value = 'template'
    newTemplateId.value = ''; resetManualForm()
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
  } catch (error) { message.value = error instanceof Error ? error.message : '读取 Agent 失败' }
}

function toggle(list: string[], value: string) {
  const i = list.indexOf(value); if (i >= 0) list.splice(i, 1); else list.push(value)
}
function manualToggleSkill(skillName: string) {
  toggle(manualSkills.value, skillName)
}

async function createFromTemplate() {
  if (!props.projectId || !newTemplateId.value) { message.value = '请选择 Agent 模板'; return }
  saving.value = true; message.value = ''
  try {
    await api.addProjectAgent(props.projectId, { template_id: newTemplateId.value })
    message.value = 'Agent 已创建'; emit('saved')
    const tmpl = templates.value.find(t => (t.id || t.name) === newTemplateId.value)
    if (tmpl) selectedName.value = tmpl.name
  } catch (error) { message.value = error instanceof Error ? error.message : '创建失败' }
  finally { saving.value = false }
}

async function createManual() {
  if (!props.projectId || !manualName.value.trim()) { message.value = '请输入 Agent 名称'; return }
  saving.value = true; message.value = ''
  const agentName = manualName.value.trim()
  try {
    await api.addProjectAgent(props.projectId, {
      name: agentName, display_name: manualDisplayName.value || agentName,
      agent_type: manualAgentType.value, sub_dir: manualSubDir.value, system_prompt: manualPrompt.value,
      description: manualDescription.value,
      model: manualAgentType.value === 'rag' || manualAgentType.value === 'chat' ? manualModel.value : undefined,
      skills: manualSkills.value,
    })
    message.value = 'Agent 已创建'; emit('saved')
    selectedName.value = agentName
  } catch (error) { message.value = error instanceof Error ? error.message : '创建失败' }
  finally { saving.value = false }
}

async function save() {
  if (!props.projectId || !form.id) { message.value = '请先选择或创建一个 Agent'; return }
  saving.value = true; message.value = ''
  try {
    const payload: Record<string, unknown> = {
      display_name: form.display_name, description: form.description,
      role: form.role, system_prompt: form.prompt, skills: form.skills,
      capabilities: form.capabilities, limitations: form.limitations,
      preferred_tasks: form.preferred_tasks, forbidden_tasks: form.forbidden_tasks,
      input_contract: form.input_contract, output_contract: form.output_contract,
      dependencies_info: form.dependencies_info, priority: form.priority,
      max_iterations: form.max_iterations,
    }
    if (form.agent_type === 'claude') { payload.sub_dir = form.sub_dir }
    if (form.agent_type === 'rag' || form.agent_type === 'chat') { payload.model = form.model }
    await api.updateProjectAgent(props.projectId, form.id, payload)
    message.value = 'Agent 配置已保存'; emit('saved')
  } catch (error) { message.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}

async function deleteAgent() {
  if (!props.projectId || !form.id) return
  if (!confirm(`确定删除 Agent "${form.display_name || form.name}"？此操作不可恢复。`)) return
  deleting.value = true; message.value = ''
  try {
    await api.deleteProjectAgent(props.projectId, form.id)
    reset(); selectedName.value = codingAgents.value[0]?.name || '__new__'
    message.value = 'Agent 已删除'; emit('saved')
  } catch (error) { message.value = error instanceof Error ? error.message : '删除失败' }
  finally { deleting.value = false }
}

watch(selectedName, select, { immediate: true })
watch(() => props.projectId, (pid) => { if (pid && selectedName.value && selectedName.value !== '__new__') select(selectedName.value) })
</script>

<template>
  <div class="d-flex flex-column gap-3">
    <ElAlert v-if="!projectId" type="info" :closable="false">
      请先在左侧选择一个项目，然后在这里配置 Agent。
    </ElAlert>

    <template v-else>
      <!-- Agent selector pills -->
      <div>
        <label class="form-label">Agent 列表</label>
        <div class="d-flex flex-wrap gap-1">
          <ElButton size="small" :type="selectedName === '__new__' ? 'primary' : ''" @click="select('__new__')">＋ 新增</ElButton>
          <ElButton v-for="agent in codingAgents" :key="agent.name" size="small"
            :type="selectedName === agent.name ? 'primary' : ''"
            @click="select(agent.name)">
            {{ agent.display_name || agent.name }}
          </ElButton>
        </div>
      </div>

      <!-- New agent form -->
      <ElCard v-if="showNewForm">
        <template #header>
          <div class="d-flex align-items-center gap-2">
            <ElIcon><Plus /></ElIcon>
            <span><strong>创建新 Agent</strong></span>
          </div>
        </template>

        <ElButtonGroup class="mb-3">
          <ElButton size="small" :type="createMode === 'template' ? 'primary' : ''" @click="createMode = 'template'">从模板创建</ElButton>
          <ElButton size="small" :type="createMode === 'manual' ? 'primary' : ''" @click="createMode = 'manual'">手动创建</ElButton>
        </ElButtonGroup>

        <template v-if="createMode === 'template'">
          <div class="mb-3">
            <label class="form-label">选择模板</label>
            <ElSelect v-model="newTemplateId" size="small" placeholder="-- 选择模板 --">
              <ElOption v-for="t in templates" :key="t.id || t.name" :value="t.id || t.name" :label="`${t.display_name} (${agentTypeLabel(t.agent_type)})`" />
            </ElSelect>
          </div>
          <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" :closable="false" class="mb-3">{{ message }}</ElAlert>
          <ElButton type="primary" size="small" :disabled="saving" @click="createFromTemplate">
            {{ saving ? '创建中…' : '创建 Agent' }}
          </ElButton>
        </template>

        <template v-else>
          <div class="mb-3">
            <label class="form-label">Agent 类型</label>
            <div>
              <ElRadioGroup v-model="manualAgentType" size="small">
                <ElRadioButton value="rag">RAG Agent</ElRadioButton>
                <ElRadioButton value="claude">Claude Agent (SDK)</ElRadioButton>
                <ElRadioButton value="chat">Chat Agent</ElRadioButton>
              </ElRadioGroup>
            </div>
          </div>
          <div class="mb-3">
            <label class="form-label">Agent 标识名 <span class="text-secondary">(英文小写+连字符)</span></label>
            <ElInput v-model="manualName" size="small" placeholder="例如 code-reviewer" />
          </div>
          <div class="mb-3">
            <label class="form-label">显示名称</label>
            <ElInput v-model="manualDisplayName" size="small" placeholder="例如 代码审查" />
          </div>
          <div class="mb-3">
            <label class="form-label">用途说明</label>
            <ElInput v-model="manualDescription" size="small" placeholder="简要描述 Agent 的职责" />
          </div>

          <!-- RAG Agent specific -->
          <template v-if="manualAgentType === 'rag'">
            <div class="mb-3">
              <label class="form-label">模型选择</label>
              <ElSelect v-model="manualModel" size="small" placeholder="选择模型">
                <ElOption value="deepseek-v4-pro" label="deepseek-v4-pro" />
                <ElOption value="deepseek-v4-flash" label="deepseek-v4-flash" />
              </ElSelect>
            </div>
          </template>

          <!-- Claude Agent specific -->
          <template v-if="manualAgentType === 'claude'">
            <div class="mb-3">
              <label class="form-label">工作子目录</label>
              <ElInput v-model="manualSubDir" size="small" placeholder="例如 frontend（可选）" />
            </div>
          </template>

          <!-- Chat Agent specific -->
          <template v-if="manualAgentType === 'chat'">
            <div class="mb-3">
              <label class="form-label">模型选择</label>
              <ElSelect v-model="manualModel" size="small" placeholder="选择模型">
                <ElOption value="deepseek-v4-pro" label="deepseek-v4-pro" />
                <ElOption value="deepseek-v4-flash" label="deepseek-v4-flash" />
              </ElSelect>
            </div>
          </template>

          <div v-if="skills.length" class="mb-3">
            <label class="form-label">关联 Skill</label>
            <div class="d-flex flex-wrap gap-2">
              <ElCheckbox v-for="skill in skills" :key="skill.name" size="small"
                :model-value="manualSkills.includes(skill.name)"
                @change="manualToggleSkill(skill.name)" :title="skill.description">
                {{ skill.name }}
              </ElCheckbox>
            </div>
          </div>

          <div class="mb-3">
            <label class="form-label">系统提示词 <span class="text-secondary">(可选)</span></label>
            <ElInput v-model="manualPrompt" type="textarea" size="small" :rows="4" placeholder="留空则使用默认提示词" />
          </div>
          <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" :closable="false" class="mb-3">{{ message }}</ElAlert>
          <ElButton type="primary" size="small" :disabled="saving" @click="createManual">
            {{ saving ? '创建中…' : '创建 Agent' }}
          </ElButton>
        </template>
      </ElCard>

      <!-- Edit form -->
      <ElCard v-else-if="selectedName !== '__new__'">
        <template #header>
          <div class="d-flex align-items-center gap-2">
            <ElIcon><UserFilled /></ElIcon>
            <span><strong>{{ agentTypeLabel(form.agent_type) }}</strong></span>
          </div>
        </template>

        <div class="mb-3">
          <label class="form-label">显示名称</label>
          <ElInput v-model="form.display_name" size="small" />
        </div>
        <div class="mb-3">
          <label class="form-label">用途说明</label>
          <ElInput v-model="form.description" size="small" />
        </div>
        <div class="mb-3">
          <label class="form-label">角色</label>
          <ElInput v-model="form.role" size="small" placeholder="implementation_agent / reviewer" />
        </div>
        <div class="row g-2 mb-3">
          <div class="col">
            <label class="form-label">优先级（0-10）</label>
            <ElInputNumber v-model="form.priority" :min="0" :max="10" size="small" />
          </div>
          <div class="col">
            <label class="form-label">最大迭代次数</label>
            <ElInputNumber v-model="form.max_iterations" :min="1" :max="20" size="small" />
          </div>
        </div>
        <div class="mb-3"><label class="form-label">能力</label>
          <ElSelect v-model="form.capabilities" multiple filterable allow-create default-first-option size="small" style="width:100%" placeholder="输入后回车添加" /></div>
        <div class="mb-3"><label class="form-label">限制</label>
          <ElSelect v-model="form.limitations" multiple filterable allow-create default-first-option size="small" style="width:100%" placeholder="输入后回车添加" /></div>
        <div class="mb-3"><label class="form-label">偏好任务</label>
          <ElSelect v-model="form.preferred_tasks" multiple filterable allow-create default-first-option size="small" style="width:100%" placeholder="输入后回车添加" /></div>
        <div class="mb-3"><label class="form-label">禁止任务</label>
          <ElSelect v-model="form.forbidden_tasks" multiple filterable allow-create default-first-option size="small" style="width:100%" placeholder="输入后回车添加" /></div>
        <div class="mb-3"><label class="form-label">运行依赖</label>
          <ElSelect v-model="form.dependencies_info" multiple filterable allow-create default-first-option size="small" style="width:100%" placeholder="输入后回车添加" /></div>

        <template v-if="form.agent_type === 'rag' || form.agent_type === 'chat'">
          <div class="mb-3">
            <label class="form-label">模型选择</label>
            <ElSelect v-model="form.model" size="small" placeholder="选择模型">
              <ElOption value="deepseek-v4-pro" label="deepseek-v4-pro" />
              <ElOption value="deepseek-v4-flash" label="deepseek-v4-flash" />
            </ElSelect>
          </div>
        </template>

        <template v-if="form.agent_type === 'claude'">
          <div class="mb-3">
            <label class="form-label">工作子目录</label>
            <ElInput v-model="form.sub_dir" size="small" placeholder="例如 frontend / backend" />
          </div>
        </template>

        <div class="mb-3">
          <label class="form-label">关联 Skill（{{ form.skills.length }}）</label>
          <div v-if="skills.length" class="d-flex flex-wrap gap-2">
            <ElCheckbox v-for="skill in skills" :key="skill.name" size="small" :model-value="form.skills.includes(skill.name)" @change="toggle(form.skills, skill.name)" :title="skill.description">
              {{ skill.name }}
            </ElCheckbox>
          </div>
          <p v-else class="text-secondary small">还没有 Skill，请先在「Skill 编辑」中创建。</p>
        </div>

        <div class="mb-3">
          <label class="form-label">系统提示词</label>
          <ElInput v-model="form.prompt" type="textarea" size="small" :rows="12" />
        </div>

        <ElAlert v-if="message" :type="(message.includes('失败') || message.includes('删除')) ? 'error' : 'success'" :closable="false" class="mb-3">{{ message }}</ElAlert>
        <div class="d-flex gap-2">
          <ElButton type="danger" size="small" :disabled="deleting" @click="deleteAgent">{{ deleting ? '删除中…' : '删除 Agent' }}</ElButton>
          <ElButton type="primary" size="small" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存 Agent' }}</ElButton>
        </div>
      </ElCard>
    </template>
  </div>
</template>
