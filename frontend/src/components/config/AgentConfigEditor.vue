<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../../api/client'
import type { AgentDetail, AgentProfile, SkillProfile } from '../../types'

const props = defineProps<{ agents: AgentProfile[]; skills: SkillProfile[] }>()
const emit = defineEmits<{ saved: [] }>()
const knownTools = ['Read', 'Glob', 'Grep', 'Write', 'Edit', 'Bash', 'Skill']
const selectedName = ref('')
const saving = ref(false)
const message = ref('')
const form = reactive<AgentDetail>({
  name: '', description: '', tools: [], skills: [], skill_count: 0, builtin: true, prompt: '',
})

async function load(name: string) {
  if (!name) return
  message.value = ''
  try {
    Object.assign(form, await api.agent(name))
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
  saving.value = true
  message.value = ''
  try {
    await api.updateAgent(form.name, {
      description: form.description,
      tools: form.tools,
      skills: form.skills,
      prompt: form.prompt,
    })
    message.value = 'Agent 配置已保存，下一次节点执行时生效。'
    emit('saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

watch(
  () => props.agents,
  (agents) => {
    if (!selectedName.value && agents[0]) selectedName.value = agents[0].name
  },
  { immediate: true },
)
watch(selectedName, load, { immediate: true })
</script>

<template>
  <div class="config-editor">
    <label class="field-label">选择 Agent</label>
    <div class="config-selector">
      <button
        v-for="agent in agents"
        :key="agent.name"
        type="button"
        :class="{ active: selectedName === agent.name }"
        @click="selectedName = agent.name"
      >
        {{ agent.name }} <small>内置 · {{ agent.skill_count }} Skill</small>
      </button>
    </div>

    <p class="builtin-note">内置 Agent 可编辑但不能删除或改名，始终由系统预加载。</p>

    <label class="field-label" for="agent-description">用途说明</label>
    <input id="agent-description" v-model="form.description" class="config-input" />

    <span class="field-label">预批准工具</span>
    <div class="choice-grid">
      <label v-for="tool in knownTools" :key="tool">
        <input type="checkbox" :checked="form.tools.includes(tool)" @change="toggle(form.tools, tool)" />
        {{ tool }}
      </label>
    </div>

    <span class="field-label">关联项目 Skill（{{ form.skills.length }}）</span>
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
    <p v-else class="config-empty">还没有项目 Skill，请先在“Skill 编辑”中创建。</p>

    <label class="field-label" for="agent-prompt">Agent 系统提示词</label>
    <textarea id="agent-prompt" v-model="form.prompt" class="config-textarea" rows="14" />

    <div class="config-actions">
      <span :class="{ error: message.includes('失败') }">{{ message }}</span>
      <button type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存 Agent' }}</button>
    </div>
  </div>
</template>
