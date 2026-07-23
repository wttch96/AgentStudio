<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../../api/client'
import type { MemoryConfiguration } from '../../types'

const emit = defineEmits<{ saved: [] }>()
const configuration = reactive<MemoryConfiguration>({
  agent_sliding_window: 20,
  planner_sliding_window: 40,
  compress_trigger_tokens: 8000,
  compress_keep_recent: 20,
  summarizer_model: 'deepseek-chat',
  max_conversation_turns: 100,
  session_archive_after_hours: 24,
  importance_decay_rate: 0.95,
})
const loading = ref(true)
const saving = ref(false)
const message = ref('')

// ── 短期记忆字段 ──
const shortTermFields = [
  {
    key: 'agent_sliding_window' as const,
    label: 'Agent 滑动窗口',
    help: '每个 Agent 保留的最近消息条数。超出后触发 LLM 摘要压缩，旧消息压缩为摘要注入上下文。',
    min: 5, max: 100, unit: '条',
  },
  {
    key: 'planner_sliding_window' as const,
    label: '主脑滑动窗口',
    help: 'DeepSeek 主脑保留的最近消息条数。主脑需要更大窗口来理解跨任务上下文。',
    min: 10, max: 200, unit: '条',
  },
  {
    key: 'compress_trigger_tokens' as const,
    label: '压缩触发阈值',
    help: '当消息的估算 token 数超过此值，LangGraph 节点自动触发记忆压缩。',
    min: 2000, max: 50000, unit: 'tokens', step: 500,
  },
  {
    key: 'compress_keep_recent' as const,
    label: '压缩保留条数',
    help: '压缩时始终保留最近 N 条消息原文不被摘要替代，保证近期对话完整性。',
    min: 5, max: 50, unit: '条',
  },
]

// ── 长期记忆字段 ──
const longTermFields = [
  {
    key: 'max_conversation_turns' as const,
    label: '最大对话轮次',
    help: '单个 conversation 的最大轮次数，超出后 LangMem 自动归档旧轮次到长期记忆 Store。',
    min: 10, max: 1000, unit: '轮',
  },
  {
    key: 'session_archive_after_hours' as const,
    label: '会话归档时间',
    help: '对话闲置超过此时间后自动提取长期记忆。设为 0 禁用自动归档。',
    min: 0, max: 720, unit: '小时',
  },
]

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
    message.value = '记忆配置已保存，将从下一次运行开始生效。'
    emit('saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <div class="config-editor memory-editor">
    <!-- 短期记忆 -->
    <section class="memory-section">
      <div class="scheduler-intro">
        <span class="junction-symbol" aria-hidden="true">&#x26A1;</span>
        <div>
          <strong>短期记忆 · 会话内</strong>
          <p>控制单个会话内的 Agent 和主脑记忆窗口、滑动窗口压缩策略。由 LangGraph 节点在每轮 wave 后自动执行。</p>
        </div>
      </div>

      <div class="scheduler-grid" :class="{ loading }">
        <label v-for="field in shortTermFields" :key="field.key" class="scheduler-field">
          <span>{{ field.label }}</span>
          <div>
            <input
              v-model.number="configuration[field.key]"
              type="number"
              :min="field.min"
              :max="field.max"
              :step="(field as any).step || 1"
              :disabled="loading"
            />
            <small>{{ field.unit }}</small>
          </div>
          <p>{{ field.help }}</p>
        </label>
      </div>

      <!-- 摘要模型 -->
      <div class="model-section">
        <label class="scheduler-field">
          <span>摘要模型</span>
          <div>
            <input v-model="configuration.summarizer_model" type="text" :disabled="loading" class="model-input" />
          </div>
          <p>用于生成记忆摘要的 LLM 模型。默认 deepseek-chat，成本极低。</p>
        </label>
      </div>

      <!-- 衰减率 -->
      <div class="decay-section">
        <label class="scheduler-field">
          <span>记忆重要性衰减率</span>
          <div>
            <input v-model.number="configuration.importance_decay_rate" type="range" min="0.5" max="1.0" step="0.01" :disabled="loading" class="decay-slider" />
            <small>{{ (configuration.importance_decay_rate * 100).toFixed(0) }}%</small>
          </div>
          <p>每次压缩后记忆重要性乘以衰减率。值越接近 1.0，旧记忆保留越久。</p>
        </label>
      </div>

      <!-- 预估 -->
      <div class="memory-estimate">
        <strong>短期记忆预估</strong>
        <div class="estimate-grid">
          <div><span>Agent 层</span><span>~{{ configuration.agent_sliding_window * 200 }} tokens / agent</span></div>
          <div><span>主脑层</span><span>~{{ configuration.planner_sliding_window * 200 }} tokens</span></div>
          <div><span>压缩触发</span><span>{{ configuration.compress_trigger_tokens.toLocaleString() }} tokens</span></div>
          <div><span>摘要开销</span><span>~200-500 tokens / 次</span></div>
        </div>
      </div>
    </section>

    <!-- 长期记忆 -->
    <section class="memory-section">
      <div class="scheduler-intro">
        <span class="junction-symbol" aria-hidden="true">&#x1F4BE;</span>
        <div>
          <strong>长期记忆 · 跨会话</strong>
          <p>控制跨会话的记忆提取、归档和持久化策略。由 LangMem create_memory_store_manager 在每次运行结束后自动执行。</p>
        </div>
      </div>

      <div class="scheduler-grid" :class="{ loading }">
        <label v-for="field in longTermFields" :key="field.key" class="scheduler-field">
          <span>{{ field.label }}</span>
          <div>
            <input
              v-model.number="configuration[field.key]"
              type="number"
              :min="field.min"
              :max="field.max"
              :step="(field as any).step || 1"
              :disabled="loading"
            />
            <small>{{ field.unit }}</small>
          </div>
          <p>{{ field.help }}</p>
        </label>
      </div>

      <div class="memory-estimate">
        <strong>长期记忆预估</strong>
        <div class="estimate-grid">
          <div><span>每会话摘要</span><span>~300-800 tokens</span></div>
          <div><span>记忆库上限</span><span>{{ configuration.max_conversation_turns }} 轮 / 会话</span></div>
          <div><span>归档延迟</span><span>{{ configuration.session_archive_after_hours }}h</span></div>
          <div><span>LangMem Store</span><span>namespace: agent_studio::long_term</span></div>
        </div>
      </div>
    </section>

    <div class="config-actions">
      <span :class="{ error: message.includes('失败') || message.includes('无效') }">{{ message }}</span>
      <button type="button" :disabled="saving || loading" @click="save">
        {{ saving ? '保存中…' : '保存记忆配置' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.memory-editor { display: flex; flex-direction: column; gap: 1.25rem; }
.memory-section {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  display: flex; flex-direction: column; gap: 0.75rem;
}
.decay-slider { flex: 1; max-width: 300px; }
.model-input { width: 250px; padding: 0.25rem 0.5rem; border: 1px solid var(--border); border-radius: 4px; font-size: 0.9rem; }
.memory-estimate { background: var(--bg-secondary, #f5f5f5); border-radius: 6px; padding: 0.75rem 1rem; }
.estimate-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-top: 0.5rem; font-size: 0.85rem; }
.estimate-grid > div { display: flex; justify-content: space-between; }
.estimate-grid > div > span:first-child { color: var(--text-secondary); }
</style>
