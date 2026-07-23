<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
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
  <div class="config-editor brain-editor">
    <div class="brain-intro">
      <span class="junction-symbol" aria-hidden="true">&#x25C7;</span>
      <div>
        <strong>DeepSeek 主脑编排</strong>
        <p>统一的多 Agent 编排提示词。主脑在持续对话中理解目标、分析空间、分解任务、调度 Agent、验收结果，并在每次用户引导时重新评估计划。</p>
      </div>
      <button type="button" :disabled="loading || saving" @click="loadDefault">加载默认配置</button>
    </div>

    <label class="field-label" for="brain-prompt">编排提示词</label>
    <textarea
      id="brain-prompt"
      v-model="configuration.orchestration_prompt"
      class="config-textarea brain-prompt"
      :disabled="loading"
      rows="20"
    />
    <p class="field-help">
      包含规划、分发、验收、引导响应等全部编排逻辑。Agent 白名单和 schema 约束由后端追加。
    </p>

    <div class="config-actions">
      <span :class="{ error: message.includes('失败') || message.includes('无效') }">{{ message }}</span>
      <button type="button" :disabled="saving || loading" @click="save">
        {{ saving ? '保存中…' : '保存主脑配置' }}
      </button>
    </div>
  </div>
</template>
