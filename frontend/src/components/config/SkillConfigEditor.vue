<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { EditPen } from '@element-plus/icons-vue'
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
  toast.value = text; toastError.value = isError
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3000)
}

function reset() { Object.assign(form, { name: '', description: '', content: '' }); message.value = '' }

async function select(name: string) {
  selectedName.value = name
  if (name === '__new__') return reset()
  try { Object.assign(form, await api.skill(name, props.projectId || undefined)) }
  catch (error) { message.value = error instanceof Error ? error.message : '读取 Skill 失败' }
}

async function save() {
  saving.value = true; message.value = ''
  try {
    if (selectedName.value === '__new__') {
      await api.createSkill({ ...form, project_id: props.projectId || '' })
      selectedName.value = form.name
    } else {
      await api.updateSkill(form.name, { description: form.description, content: form.content }, props.projectId || undefined)
    }
    showToast('Skill 已保存。'); emit('saved')
  } catch (error) {
    showToast(error instanceof Error ? error.message : '保存失败', true)
  } finally { saving.value = false }
}

watch(() => props.skills, (skills) => {
  if (selectedName.value !== '__new__' && !skills.some((item) => item.name === selectedName.value)) reset()
})
</script>

<template>
  <div class="d-flex flex-column gap-3">
    <div class="d-flex align-items-center gap-2">
      <label class="form-label mb-0">选择或新增 Skill</label>
      <ElTag v-if="projectId" type="info" size="small">项目级</ElTag>
      <ElTag v-else type="info" size="small">全局</ElTag>
    </div>

    <div class="d-flex flex-wrap gap-1">
      <ElButton size="small" :type="selectedName === '__new__' ? 'primary' : ''" @click="select('__new__')">＋ 新建</ElButton>
      <ElButton v-for="skill in skills" :key="skill.name" size="small" :type="selectedName === skill.name ? 'primary' : ''" @click="select(skill.name)">
        {{ skill.name }}
      </ElButton>
    </div>

    <ElCard>
      <template #header>
        <div class="d-flex align-items-center gap-2">
          <ElIcon size="20"><EditPen /></ElIcon>
          <span><strong>{{ selectedName === '__new__' ? '新建 Skill' : selectedName }}</strong></span>
        </div>
      </template>

      <div class="mb-3">
        <label class="form-label">Skill 名称</label>
        <ElInput v-model="form.name" size="small" :disabled="selectedName !== '__new__'" placeholder="例如 netty-protocol" />
        <div class="form-text">只能使用小写字母、数字和短横线。</div>
      </div>
      <div class="mb-3">
        <label class="form-label">用途说明</label>
        <ElInput v-model="form.description" size="small" />
      </div>
      <div class="mb-3">
        <label class="form-label">Skill 指令正文</label>
        <ElInput v-model="form.content" type="textarea" size="small" :rows="17" placeholder="写明何时使用、执行步骤、约束和验证方法…" />
      </div>
      <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" :closable="false" class="mb-3">{{ message }}</ElAlert>
      <ElButton type="primary" size="small" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存 Skill' }}</ElButton>
    </ElCard>

    <!-- Toast -->
    <Transition name="toast">
      <div v-if="toast" class="position-fixed bottom-0 end-0 m-3 p-2 rounded small" :class="toastError ? 'bg-danger text-white' : 'bg-success text-white'" role="alert">
        {{ toast }}
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: opacity 0.3s, transform 0.3s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(10px); }
</style>
