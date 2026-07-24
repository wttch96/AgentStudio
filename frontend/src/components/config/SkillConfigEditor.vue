<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../../api/client'
import type { SkillProfile } from '../../types'

const props = defineProps<{ skills: SkillProfile[]; projectId: string }>()
const emit = defineEmits<{ saved: [] }>()
const selectedName = ref('__new__')
const saving = ref(false)
const message = ref('')
const toast = ref('')
const toastError = ref(false)
let toastTimer: ReturnType<typeof setTimeout> | null = null
const form = reactive<Required<SkillProfile>>({ name: '', description: '', content: '' })

function showToast(text: string, isError = false) {
  toast.value = text
  toastError.value = isError
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3000)
}

function reset() {
  Object.assign(form, { name: '', description: '', content: '' })
  message.value = ''
}

async function select(name: string) {
  selectedName.value = name
  if (name === '__new__') return reset()
  try {
    Object.assign(form, await api.skill(name, props.projectId || undefined))
  } catch (error) {
    message.value = error instanceof Error ? error.message : '读取 Skill 失败'
  }
}

async function save() {
  saving.value = true
  message.value = ''
  try {
    if (selectedName.value === '__new__') {
      await api.createSkill({ ...form, project_id: props.projectId || '' })
      selectedName.value = form.name
    } else {
      await api.updateSkill(form.name, { description: form.description, content: form.content }, props.projectId || undefined)
    }
    showToast('Skill 已保存，可在 Agent 配置中关联。')
    emit('saved')
  } catch (error) {
    const msg = error instanceof Error ? error.message : '保存失败'
    showToast(msg, true)
  } finally {
    saving.value = false
  }
}

watch(
  () => props.skills,
  (skills) => {
    if (selectedName.value !== '__new__' && !skills.some((item) => item.name === selectedName.value)) reset()
  },
)
</script>

<template>
  <div class="config-editor">
    <label class="field-label">选择或新增 Skill<span v-if="projectId" class="storage-badge">项目级</span><span v-else class="storage-badge global">全局</span></label>
    <div class="config-selector">
      <button type="button" :class="{ active: selectedName === '__new__' }" @click="select('__new__')">＋ 新建</button>
      <button
        v-for="skill in skills"
        :key="skill.name"
        type="button"
        :class="{ active: selectedName === skill.name }"
        @click="select(skill.name)"
      >{{ skill.name }}</button>
    </div>

    <label class="field-label" for="skill-name">Skill 名称</label>
    <input
      id="skill-name"
      v-model="form.name"
      class="config-input"
      :disabled="selectedName !== '__new__'"
      placeholder="例如 netty-protocol"
      pattern="[a-z][a-z0-9-]+"
    />
    <p class="field-help">只能使用小写字母、数字和短横线；保存后对应 `.claude/skills/名称/SKILL.md`。</p>

    <label class="field-label" for="skill-description">用途说明</label>
    <input id="skill-description" v-model="form.description" class="config-input" />

    <label class="field-label" for="skill-content">Skill 指令正文</label>
    <textarea
      id="skill-content"
      v-model="form.content"
      class="config-textarea"
      rows="17"
      placeholder="写明何时使用、执行步骤、约束和验证方法…"
    />

    <div class="config-actions">
      <span :class="{ error: message.includes('失败') }">{{ message }}</span>
      <button type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存 Skill' }}</button>
    </div>

    <!-- Toast -->
    <Transition name="toast">
      <div v-if="toast" :class="['skill-toast', { 'toast-error': toastError }]" role="alert">
        {{ toast }}
      </div>
    </Transition>
  </div>
</template>
