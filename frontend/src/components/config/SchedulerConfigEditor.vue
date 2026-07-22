<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../../api/client'
import type { SchedulerConfiguration } from '../../types'

const emit = defineEmits<{ saved: [] }>()
const configuration = reactive<SchedulerConfiguration>({
  max_concurrent_agents: 3,
  recursion_limit: 100,
  agent_max_turns: 12,
  agent_timeout_seconds: 900,
})
const loading = ref(true)
const saving = ref(false)
const message = ref('')

const fields = [
  {
    key: 'max_concurrent_agents',
    label: '最大并行 Agent',
    help: '同一批次最多同时运行多少个 Claude Agent。',
    min: 1,
    max: 8,
    unit: '个',
  },
  {
    key: 'recursion_limit',
    label: '图递归上限',
    help: '限制一次 LangGraph 运行允许经过的总步骤，深层 DAG 需要更高值。',
    min: 10,
    max: 500,
    unit: '步',
  },
  {
    key: 'agent_max_turns',
    label: 'Agent 最大轮次',
    help: '限制每个 Claude Agent 在单个任务节点中的自主工具交互轮次。',
    min: 1,
    max: 100,
    unit: '轮',
  },
  {
    key: 'agent_timeout_seconds',
    label: 'Agent 超时时间',
    help: '单个节点超过此时间后返回失败，其他无依赖节点仍可完成。',
    min: 30,
    max: 7200,
    unit: '秒',
  },
] as const

async function load() {
  loading.value = true
  message.value = ''
  try {
    Object.assign(configuration, await api.scheduler())
  } catch (error) {
    message.value = error instanceof Error ? error.message : '调度配置读取失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  message.value = ''
  try {
    Object.assign(configuration, await api.updateScheduler({ ...configuration }))
    message.value = '调度配置已保存，将从下一次运行开始生效。'
    emit('saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="config-editor scheduler-editor">
    <div class="scheduler-intro">
      <span class="junction-symbol" aria-hidden="true">⑂</span>
      <div>
        <strong>分流、并行与汇流</strong>
        <p>配置在每次运行开始时生成快照，不会改变正在执行的任务。</p>
      </div>
    </div>

    <div class="scheduler-grid" :class="{ loading }">
      <label v-for="field in fields" :key="field.key" class="scheduler-field">
        <span>{{ field.label }}</span>
        <div>
          <input
            v-model.number="configuration[field.key]"
            type="number"
            :min="field.min"
            :max="field.max"
            :disabled="loading"
          />
          <small>{{ field.unit }}</small>
        </div>
        <p>{{ field.help }}</p>
      </label>
    </div>

    <div class="turn-recommendation">
      <div>
        <strong>轮次建议</strong>
        <span>简单任务 12–20 轮；跨目录分析或大型修改建议 30–60 轮。提高后会增加耗时与模型费用。</span>
      </div>
      <button type="button" :disabled="loading" @click="configuration.agent_max_turns = 30">
        使用 30 轮
      </button>
    </div>

    <div class="scheduler-policy">
      <strong>固定执行策略</strong>
      <span>依赖失败时阻塞下游；独立节点继续；当前批次全部结束后才汇流。</span>
    </div>

    <div class="config-actions">
      <span :class="{ error: message.includes('失败') || message.includes('无效') }">{{ message }}</span>
      <button type="button" :disabled="saving || loading" @click="save">
        {{ saving ? '保存中…' : '保存调度配置' }}
      </button>
    </div>
  </div>
</template>
