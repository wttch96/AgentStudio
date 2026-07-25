<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Timer } from '@element-plus/icons-vue'
import { api } from '../../api/client'
import type { SchedulerConfiguration } from '../../types'

const emit = defineEmits<{ saved: [] }>()
const configuration = reactive<SchedulerConfiguration>({
  max_concurrent_agents: 3, recursion_limit: 100, agent_max_turns: 12, agent_timeout_seconds: 900,
})
const loading = ref(true)
const saving = ref(false)
const message = ref('')

const fields = [
  { key: 'max_concurrent_agents' as const, label: '最大并行 Agent', help: '同一批次最多同时运行多少个 Claude Agent。', min: 1, max: 8, unit: '个' },
  { key: 'recursion_limit' as const, label: '图递归上限', help: '限制一次 LangGraph 运行允许经过的总步骤。', min: 10, max: 500, unit: '步' },
  { key: 'agent_max_turns' as const, label: 'Agent 最大轮次', help: '每个 Claude Agent 在单任务中的自主工具交互轮次。', min: 1, max: 100, unit: '轮' },
  { key: 'agent_timeout_seconds' as const, label: 'Agent 超时时间', help: '单个节点超过此时间后返回失败。', min: 30, max: 7200, unit: '秒' },
]

async function load() {
  loading.value = true; message.value = ''
  try { Object.assign(configuration, await api.scheduler()) }
  catch (error) { message.value = error instanceof Error ? error.message : '调度配置读取失败' }
  finally { loading.value = false }
}

async function save() {
  saving.value = true; message.value = ''
  try {
    Object.assign(configuration, await api.updateScheduler({ ...configuration }))
    message.value = '调度配置已保存，将从下一次运行开始生效。'
    emit('saved')
  } catch (error) { message.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <ElCard>
    <template #header>
      <div class="d-flex align-items-center gap-2">
        <ElIcon size="20"><Timer /></ElIcon>
        <div>
          <strong>分流、并行与汇流</strong>
          <p class="text-secondary mb-0">配置在每次运行开始时生成快照，不会改变正在执行的任务。</p>
        </div>
      </div>
    </template>

    <div class="row g-3 mb-3">
      <div v-for="field in fields" :key="field.key" class="col-md-6">
        <label class="form-label">{{ field.label }}</label>
        <ElInput v-model.number="configuration[field.key]" type="number" size="small" :min="field.min" :max="field.max" :disabled="loading">
          <template #append>{{ field.unit }}</template>
        </ElInput>
        <div class="form-text">{{ field.help }}</div>
      </div>
    </div>

    <div class="d-flex align-items-center gap-2 p-2 bg-body-tertiary rounded mb-3">
      <strong class="small">轮次建议</strong>
      <span class="text-secondary small">简单任务 12–20 轮；跨目录分析建议 30–60 轮。</span>
      <ElButton size="small" class="ms-auto" :disabled="loading" @click="configuration.agent_max_turns = 30">使用 30 轮</ElButton>
    </div>

    <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" :closable="false" class="mb-3">{{ message }}</ElAlert>
    <ElButton type="primary" size="small" :disabled="saving || loading" @click="save">{{ saving ? '保存中…' : '保存调度配置' }}</ElButton>
  </ElCard>
</template>
