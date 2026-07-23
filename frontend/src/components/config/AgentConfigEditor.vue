<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../../api/client'
import type { AgentDetail, AgentProfile, SkillProfile } from '../../types'

const props = defineProps<{ agents: AgentProfile[]; skills: SkillProfile[]; projectId: string }>()
const emit = defineEmits<{ saved: [] }>()
const knownTools = ['Read', 'Glob', 'Grep', 'Write', 'Edit', 'Bash', 'Skill']
const selectedName = ref('')
const saving = ref(false)
const message = ref('')
const form = reactive<AgentDetail & { id: string; sub_dir: string; display_name: string }>({
  id: '', name: '', display_name: '', description: '', tools: [], skills: [],
  skill_count: 0, builtin: false, prompt: '', sub_dir: '',
})

const codingAgents = ref<AgentProfile[]>([])
watch(() => props.agents, (agents) => {
  codingAgents.value = agents.filter(a => a.name !== 'brain' && a.name !== 'knowledge-rag')
  if (!selectedName.value && codingAgents.value[0]) {
    selectedName.value = codingAgents.value[0].name
  }
}, { immediate: true })

async function load(name: string) {
  if (!name || !props.projectId) return
  message.value = ''
  try {
    const detail = await api.agent(name, props.projectId)
    Object.assign(form, detail)
    const agent = codingAgents.value.find(a => a.name === name)
    if (agent) form.id = agent.id || ''
  } catch (error) {
    message.value = error instanceof Error ? error.message : '读取 Agent 失败'
  }
}

function toggle(list: string[], value: string) {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

async function save() {
  if (!props.projectId || !form.id) {
    message.value = '请先在项目管理中创建 Agent'
    return
  }
  saving.value = true
  message.value = ''
  try {
    await api.updateProjectAgent(props.projectId, form.id, {
      display_name: form.display_name,
      description: form.description,
      tools: form.tools,
      skills: form.skills,
      system_prompt: form.prompt,
      sub_dir: form.sub_dir,
    })
    message.value = 'Agent 配置已保存'
    emit('saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

watch(selectedName, load, { immediate: true })
</script>

<template>
  <div class="config-editor">
    <div v-if="!projectId" class="config-empty">
      请先在顶部选择一个项目，然后在这里配置该项目下的 Coding Agent。
    </div>
    <template v-else>
      <label class="field-label">Coding Agent（Claude Agent SDK）</label>
      <div v-if="!codingAgents.length" class="config-empty">
        还没有 Coding Agent，请通过顶部「项目管理」为当前项目添加 Agent。
      </div>
      <div v-else class="config-selector">
        <button
          v-for="agent in codingAgents"
          :key="agent.name"
          type="button"
          :class="{ active: selectedName === agent.name }"
          @click="selectedName = agent.name"
        >
          {{ agent.display_name || agent.name }}
          <small>{{ agent.sub_dir || '根目录' }} · {{ agent.skill_count }} Skill</small>
        </button>
      </div>

      <label class="field-label" for="agent-description">用途说明</label>
      <input id="agent-description" v-model="form.description" class="config-input" />

      <label class="field-label" for="agent-subdir">工作子目录</label>
      <input id="agent-subdir" v-model="form.sub_dir" class="config-input" placeholder="例如 frontend / backend" />

      <span class="field-label">预批准工具</span>
      <div class="choice-grid">
        <label v-for="tool in knownTools" :key="tool">
          <input type="checkbox" :checked="form.tools.includes(tool)" @change="toggle(form.tools, tool)" />
          {{ tool }}
        </label>
      </div>

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

      <label class="field-label" for="agent-prompt">Agent 系统提示词</label>
      <textarea id="agent-prompt" v-model="form.prompt" class="config-textarea" rows="14" />

      <div class="config-actions">
        <span :class="{ error: message.includes('失败') }">{{ message }}</span>
        <button type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存 Agent' }}</button>
      </div>
    </template>
  </div>
</template>
