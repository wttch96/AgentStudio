<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Lightning, FolderOpened } from '@element-plus/icons-vue'
import { api } from '../../api/client'
import type { MemoryConfiguration } from '../../types'

const emit = defineEmits<{ saved: [] }>()
const configuration = reactive<MemoryConfiguration>({
  compress_trigger_tokens: 8000, compress_keep_recent: 20, summarizer_model: 'deepseek-v4-pro',
  max_conversation_turns: 100, session_archive_after_hours: 24, importance_decay_rate: 0.95,
})
const loading = ref(true); const saving = ref(false); const message = ref('')

async function load() {
  loading.value = true; message.value = ''
  try { Object.assign(configuration, await api.memoryConfig()) }
  catch (error) { message.value = error instanceof Error ? error.message : '记忆配置读取失败' }
  finally { loading.value = false }
}
async function save() {
  saving.value = true; message.value = ''
  try {
    Object.assign(configuration, await api.updateMemoryConfig({ ...configuration }))
    message.value = '记忆配置已保存。'; emit('saved')
  } catch (error) { message.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <div class="d-flex flex-column gap-3">
    <!-- 短期记忆 -->
    <ElCard>
      <template #header>
        <div class="d-flex align-items-center gap-2">
          <ElIcon size="20"><Lightning /></ElIcon>
          <div>
            <strong>短期记忆 · 会话内</strong>
            <p class="text-secondary mb-0">控制单个会话内的消息压缩策略。</p>
          </div>
        </div>
      </template>

      <div class="row g-3 mb-3">
        <div class="col-md-6">
          <label class="form-label">压缩触发阈值</label>
          <ElInput v-model.number="configuration.compress_trigger_tokens" type="number" size="small" :min="2000" :max="50000" :step="500" :disabled="loading">
            <template #append>tokens</template>
          </ElInput>
          <div class="form-text">消息估算 token 数超过此值自动触发压缩。</div>
        </div>
        <div class="col-md-6">
          <label class="form-label">压缩保留条数</label>
          <ElInput v-model.number="configuration.compress_keep_recent" type="number" size="small" :min="5" :max="50" :disabled="loading">
            <template #append>条</template>
          </ElInput>
          <div class="form-text">保留最近 N 条原文不被替代。</div>
        </div>
      </div>

      <div class="mb-3">
        <label class="form-label">摘要模型</label>
        <ElInput v-model="configuration.summarizer_model" size="small" :disabled="loading" />
        <div class="form-text">用于生成记忆摘要的 LLM 模型。</div>
      </div>

      <div class="mb-3">
        <label class="form-label">重要性衰减率: {{ (configuration.importance_decay_rate * 100).toFixed(0) }}%</label>
        <ElSlider v-model="configuration.importance_decay_rate" :min="0.5" :max="1.0" :step="0.01" :disabled="loading" />
        <div class="form-text">值越接近 1.0，旧记忆保留越久。</div>
      </div>
    </ElCard>

    <!-- 长期记忆 -->
    <ElCard>
      <template #header>
        <div class="d-flex align-items-center gap-2">
          <ElIcon size="20"><FolderOpened /></ElIcon>
          <div>
            <strong>长期记忆 · 跨会话</strong>
            <p class="text-secondary mb-0">控制跨会话的记忆提取和归档策略。</p>
          </div>
        </div>
      </template>

      <div class="row g-3 mb-3">
        <div class="col-md-6">
          <label class="form-label">最大对话轮次</label>
          <ElInput v-model.number="configuration.max_conversation_turns" type="number" size="small" :min="10" :max="1000" :disabled="loading">
            <template #append>轮</template>
          </ElInput>
        </div>
        <div class="col-md-6">
          <label class="form-label">会话归档时间</label>
          <ElInput v-model.number="configuration.session_archive_after_hours" type="number" size="small" :min="0" :max="720" :disabled="loading">
            <template #append>小时</template>
          </ElInput>
        </div>
      </div>
    </ElCard>

    <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" :closable="false" class="mb-3">{{ message }}</ElAlert>
    <ElButton type="primary" size="small" :disabled="saving || loading" @click="save">{{ saving ? '保存中…' : '保存记忆配置' }}</ElButton>
  </div>
</template>
