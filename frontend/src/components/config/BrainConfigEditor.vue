<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Cpu } from '@element-plus/icons-vue'
import { api } from '../../api/client'
import type { BrainConfiguration } from '../../types'

const emit = defineEmits<{ saved: [] }>()
const configuration = reactive<BrainConfiguration>({ orchestration_prompt: '' })
const loading = ref(true)
const saving = ref(false)
const message = ref('')

async function load() {
  loading.value = true; message.value = ''
  try { Object.assign(configuration, await api.brain()) }
  catch (error) { message.value = error instanceof Error ? error.message : '主脑配置读取失败' }
  finally { loading.value = false }
}

async function save() {
  saving.value = true; message.value = ''
  try {
    Object.assign(configuration, await api.updateBrain({ ...configuration }))
    message.value = '主脑提示词已保存。'
    emit('saved')
  } catch (error) { message.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}

async function loadDefault() {
  loading.value = true; message.value = ''
  try {
    Object.assign(configuration, await api.defaultBrain())
    message.value = '已载入默认配置，确认后请保存。'
  } catch (error) { message.value = error instanceof Error ? error.message : '默认模板读取失败' }
  finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <ElCard>
    <template #header>
      <div class="d-flex align-items-start gap-3">
        <ElIcon size="20"><Cpu /></ElIcon>
        <div class="flex-grow-1">
          <strong>DeepSeek 主脑编排</strong>
          <p class="text-secondary mb-0">统一的多 Agent 编排提示词。主脑在持续对话中理解目标、分析空间、分解任务、调度 Agent、验收结果。</p>
        </div>
        <ElButton size="small" :disabled="loading || saving" @click="loadDefault">加载默认配置</ElButton>
      </div>
    </template>

    <div class="mb-3">
      <label class="form-label" for="brain-prompt">编排提示词</label>
      <ElInput id="brain-prompt" v-model="configuration.orchestration_prompt" type="textarea" class="font-monospace small" :disabled="loading" :rows="20" />
      <p class="form-text">包含规划、分发、验收、引导响应等全部编排逻辑。Agent 白名单和 schema 约束由后端追加。</p>
    </div>

    <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" :closable="false" class="mb-3">{{ message }}</ElAlert>
    <ElButton type="primary" size="small" :disabled="saving || loading" @click="save">
      {{ saving ? '保存中…' : '保存主脑配置' }}
    </ElButton>
  </ElCard>
</template>
