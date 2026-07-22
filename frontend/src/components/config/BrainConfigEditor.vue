<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../../api/client'
import type { BrainConfiguration } from '../../types'

const emit = defineEmits<{ saved: [] }>()
const configuration = reactive<BrainConfiguration>({ planning_prompt: '', summary_prompt: '' })
const loading = ref(true)
const saving = ref(false)
const message = ref('')

async function load() {
  loading.value = true
  message.value = ''
  try {
    Object.assign(configuration, await api.brain())
  } catch (error) {
    message.value = error instanceof Error ? error.message : '主脑配置读取失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  message.value = ''
  try {
    Object.assign(configuration, await api.updateBrain({ ...configuration }))
    message.value = '主脑提示词已保存，将从下一次规划开始生效。'
    emit('saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function loadDefault() {
  loading.value = true
  message.value = ''
  try {
    Object.assign(configuration, await api.defaultBrain())
    message.value = '已载入默认模板，确认内容后请点击保存。'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '默认模板读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="config-editor brain-editor">
    <div class="brain-intro">
      <span class="junction-symbol" aria-hidden="true">◇</span>
      <div>
        <strong>DeepSeek 主脑</strong>
        <p>负责读取项目发现结果、选择真实项目、定义共享契约、生成实施 DAG 并最终验收。</p>
      </div>
      <button type="button" :disabled="loading || saving" @click="loadDefault">
        加载默认配置
      </button>
    </div>

    <label class="field-label" for="brain-planning-prompt">规划与决策提示词</label>
    <textarea
      id="brain-planning-prompt"
      v-model="configuration.planning_prompt"
      class="config-textarea brain-prompt"
      :disabled="loading"
      rows="18"
    />
    <p class="field-help">
      建议保留“先发现项目、再选择项目、先定义跨项目契约、最后并行编码”的决策顺序。
    </p>

    <label class="field-label" for="brain-summary-prompt">最终验收提示词</label>
    <textarea
      id="brain-summary-prompt"
      v-model="configuration.summary_prompt"
      class="config-textarea brain-prompt"
      :disabled="loading"
      rows="8"
    />
    <p class="field-help">
      Agent 白名单、JSON Schema 和工作空间路径约束由后端固定追加，不会因编辑提示词而失效。
    </p>

    <div class="config-actions">
      <span :class="{ error: message.includes('失败') || message.includes('无效') }">{{ message }}</span>
      <button type="button" :disabled="saving || loading" @click="save">
        {{ saving ? '保存中…' : '保存主脑配置' }}
      </button>
    </div>
  </div>
</template>
