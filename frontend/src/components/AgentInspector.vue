<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { AgentProfile, DeepSeekBalance, RunEvent } from '../types'
import { api } from '../api/client'

const props = defineProps<{
  agents: AgentProfile[]
  events: RunEvent[]
  deepseekBalance: DeepSeekBalance | null
  balanceLoading: boolean
  projectId: string
}>()
defineEmits<{ refreshBalance: [] }>()
const knowledgeTotal = ref(0)
onMounted(async () => {
  try {
    const stats = await api.knowledgeStats(props.projectId || undefined)
    knowledgeTotal.value = stats.total
  } catch { /* ignore */ }
})

function currencySymbol(currency: string) {
  if (currency === 'CNY') return '¥'
  if (currency === 'USD') return '$'
  return `${currency} `
}

function formatTokens(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatCost(value: string) {
  const amount = Number(value)
  if (amount > 0 && amount < 0.000001) return '< $0.000001'
  return `$${amount.toFixed(6)}`
}

function status(name: string) {
  const events = props.events.filter((event) => event.agent_id === name)
  if (events.some((event) => event.type === 'agent.failed')) return 'failed'
  const starts = events.filter((event) => event.type === 'agent.started').length
  const finishes = events.filter((event) => event.type === 'agent.completed').length
  if (starts > finishes) return 'running'
  if (finishes) return 'completed'
  return 'idle'
}

function calls(name: string) {
  return props.events.filter(
    (event) => event.agent_id === name && event.type === 'tool.started',
  ).length
}

function loadedSkills(name: string) {
  return new Set(
    props.events
      .filter((event) => event.agent_id === name && event.type === 'skill.loaded')
      .map((event) => String(event.payload.skill ?? 'unknown')),
  ).size
}

function agentTokens(name: string) {
  let input = 0; let output = 0; let promptChars = 0; let hasUsage = false
  for (const e of props.events) {
    if (e.agent_id === name) {
      if (e.type === 'agent.prompt') {
        promptChars += (e.payload?.prompt_chars as number) || 0
      } else if (e.type === 'agent.usage') {
        input += (e.payload?.input_tokens as number) || 0
        output += (e.payload?.output_tokens as number) || 0
        hasUsage = true
      }
    }
  }
  // SDK 提供 usage 时：加上提示词估算 (chars/2 ≈ tokens)
  if (hasUsage) {
    input += Math.ceil(promptChars / 2)
  } else {
    // SDK 未提供 token 时，从文本长度估算
    for (const e of props.events) {
      if (e.agent_id === name) {
        if (e.type === 'agent.message') {
          output += Math.ceil((e.payload?.text as string || '').length / 2)
        } else if (e.type === 'tool.started') {
          input += JSON.stringify(e.payload?.input || '').length
        }
      }
    }
    input += Math.ceil(promptChars / 2)
  }
  return { input, output }
}
function formatKTokens(n: number) {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

// 系统 Agent 状态（主脑 / RAG / 记忆）
function brainStatus() {
  const events = props.events
  if (events.some(e => e.type === 'brain.synthesizing')) return 'synthesizing'
  if (events.some(e => e.type === 'planner.started')) return 'planning'
  if (events.some(e => e.type === 'plan.created')) return 'planned'
  return 'idle'
}
function brainActivity() {
  const plans = props.events.filter(e => e.type === 'plan.created').length
  const contracts = props.events.filter(e => e.type === 'brain.contract_created').length
  return { plans, contracts }
}
function memoryActivity() {
  const compacted = props.events.filter(e => e.type === 'memory.compacted').length
  const extracted = props.events.filter(e => e.type === 'memory.extracted').length
  return { compacted, extracted }
}
function ragActivity() {
  const searches = props.events.filter(e => e.agent_id && e.type === 'tool.started' && e.payload?.tool === 'search_knowledge').length
  const adds = props.events.filter(e => e.agent_id && e.type === 'tool.started' && e.payload?.tool === 'add_knowledge').length
  const started = props.events.some(e => e.agent_id && e.type === 'agent.started' && props.agents.some(a => a.name === e.agent_id && a.agent_type === 'rag'))
  return { searches, adds, active: started, total: knowledgeTotal.value }
}
function ragStatus() {
  const events = props.events
  if (events.some(e => e.agent_id && e.type === 'agent.failed' && props.agents.some(a => a.name === e.agent_id && a.agent_type === 'rag'))) return 'failed'
  const starts = events.filter(e => e.agent_id && e.type === 'agent.started' && props.agents.some(a => a.name === e.agent_id && a.agent_type === 'rag')).length
  const finishes = events.filter(e => e.agent_id && e.type === 'agent.completed' && props.agents.some(a => a.name === e.agent_id && a.agent_type === 'rag')).length
  if (starts > finishes) return 'running'
  if (finishes) return 'completed'
  return 'idle'
}
function memoryStatus() {
  if (props.events.some(e => e.type === 'memory.extracted')) return 'completed'
  if (props.events.some(e => e.type === 'memory.compacted')) return 'compacting'
  return 'idle'
}
</script>

<template>
  <aside class="inspector">
    <div class="inspector-heading">
      <div>
        <span class="eyebrow">专业团队</span>
        <h2>Agent 状态</h2>
      </div>
      <span class="agent-count">{{ agents.length }}</span>
    </div>
    <div class="agent-stack">
      <article v-for="agent in agents.filter(a => a.agent_type !== 'rag')" :key="agent.name" class="agent-card" :class="status(agent.name)">
        <div class="agent-avatar">{{ agent.name.charAt(0).toUpperCase() }}</div>
        <div class="agent-card-copy">
          <strong>{{ agent.name }}</strong>
          <span v-if="agent.builtin" class="builtin-badge">内置</span>
          <p>{{ agent.description }}</p>
          <div class="agent-meta">
            <span class="mini-status"><i />{{ status(agent.name) }}</span>
            <span>配置 {{ agent.skill_count }}</span>
            <span>本次加载 {{ loadedSkills(agent.name) }}</span>
            <span v-if="calls(agent.name)">{{ calls(agent.name) }} 次工具</span>
            <span class="token-stat">入 {{ formatKTokens(agentTokens(agent.name).input) }} / 出 {{ formatKTokens(agentTokens(agent.name).output) }} token</span>
          </div>
        </div>
      </article>
    </div>
    <!-- 系统 Agent：主脑 / RAG / 记忆 -->
    <div class="inspector-heading" style="margin-top:12px">
      <div>
        <span class="eyebrow">系统 Agent</span>
        <h2>主脑 · RAG · 记忆</h2>
      </div>
    </div>
    <div class="agent-stack">
      <!-- 主脑 Agent -->
      <article class="agent-card system-agent" :class="brainStatus()">
        <div class="agent-avatar brain-avatar">B</div>
        <div class="agent-card-copy">
          <strong>主脑 (DeepSeek)</strong>
          <p>任务规划 · DAG生成 · 契约设计 · 最终验收</p>
          <div class="agent-meta">
            <span class="mini-status"><i />{{ brainStatus() }}</span>
            <span>{{ brainActivity().plans }} 次规划</span>
            <span v-if="brainActivity().contracts">{{ brainActivity().contracts }} 份契约</span>
          </div>
        </div>
      </article>
      <!-- RAG Agent -->
      <article class="agent-card system-agent" :class="ragStatus()">
        <div class="agent-avatar rag-avatar">R</div>
        <div class="agent-card-copy">
          <strong>RAG (LangChain)</strong>
          <p>知识检索 · 内容录入 · 关联管理 · 综合问答</p>
          <div class="agent-meta">
            <span class="mini-status"><i />{{ ragStatus() }}</span>
            <span>{{ ragActivity().searches }} 次检索</span>
            <span>知识库 {{ ragActivity().total }} 条</span>
            <span>{{ ragActivity().searches }} 次检索</span>
            <span v-if="ragActivity().adds">{{ ragActivity().adds }} 条录入</span>
          </div>
        </div>
      </article>
      <!-- 记忆 Agent -->
      <article class="agent-card system-agent" :class="memoryStatus()">
        <div class="agent-avatar memory-avatar">M</div>
        <div class="agent-card-copy">
          <strong>记忆管理 (LangMem)</strong>
          <p>滑动窗口压缩 · 跨会话提取 · 重要性衰减</p>
          <div class="agent-meta">
            <span class="mini-status"><i />{{ memoryStatus() }}</span>
            <span>{{ memoryActivity().compacted }} 次压缩</span>
            <span v-if="memoryActivity().extracted">{{ memoryActivity().extracted }} 次提取</span>
          </div>
        </div>
      </article>
    </div>
    <section class="balance-panel">
      <header>
        <div>
          <span class="eyebrow">DeepSeek API</span>
          <strong>账户余额</strong>
        </div>
        <ElButton
          link
          size="small"
          :disabled="balanceLoading"
          title="刷新账户余额"
          aria-label="刷新 DeepSeek 账户余额"
          @click="$emit('refreshBalance')"
        >
          {{ balanceLoading ? '…' : '↻' }}
        </ElButton>
      </header>

      <div v-if="deepseekBalance" class="balance-content">
        <div v-if="deepseekBalance.infos.length" class="balance-list">
          <div v-for="item in deepseekBalance.infos" :key="item.currency" class="balance-item">
            <div class="balance-row">
              <span>可用余额 · {{ item.currency }}</span>
              <strong>{{ currencySymbol(item.currency) }}{{ item.total_balance }}</strong>
            </div>
            <div class="balance-breakdown">
              <span>充值 {{ currencySymbol(item.currency) }}{{ item.topped_up_balance }}</span>
              <span>赠金 {{ currencySymbol(item.currency) }}{{ item.granted_balance }}</span>
            </div>
          </div>
        </div>
        <div v-else-if="!deepseekBalance.error" class="balance-row">
          <span>可用余额</span>
          <strong>不可用</strong>
        </div>
        <p v-if="deepseekBalance.error" class="balance-error" :title="deepseekBalance.error">
          {{ deepseekBalance.configured ? `余额查询失败：${deepseekBalance.error}` : '尚未配置 DeepSeek' }}
        </p>
      </div>
      <div v-else class="balance-loading">正在读取余额…</div>

    </section>
  </aside>
</template>
