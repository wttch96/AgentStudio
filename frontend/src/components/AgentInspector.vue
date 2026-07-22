<script setup lang="ts">
import type { AgentProfile, DeepSeekBalance, DeepSeekUsage, RunEvent } from '../types'

const props = defineProps<{
  agents: AgentProfile[]
  events: RunEvent[]
  deepseekBalance: DeepSeekBalance | null
  deepseekUsage: DeepSeekUsage | null
  balanceLoading: boolean
}>()
defineEmits<{ refreshBalance: [] }>()

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
      <article v-for="agent in agents" :key="agent.name" class="agent-card" :class="status(agent.name)">
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
          </div>
        </div>
      </article>
    </div>
    <div class="model-panel">
      <span class="eyebrow">调度层</span>
      <div><strong>DeepSeek</strong><span>规划 · 路由 · 决策</span></div>
      <div><strong>LangGraph</strong><span>DAG · 并行 · 汇合</span></div>
    </div>
    <section class="balance-panel">
      <header>
        <div>
          <span class="eyebrow">DeepSeek API</span>
          <strong>账户余额</strong>
        </div>
        <button
          type="button"
          :disabled="balanceLoading"
          title="刷新账户余额"
          aria-label="刷新 DeepSeek 账户余额"
          @click="$emit('refreshBalance')"
        >
          {{ balanceLoading ? '…' : '↻' }}
        </button>
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

      <div v-if="deepseekUsage" class="local-usage">
        <div class="local-usage-heading">
          <strong>Token 与花费</strong>
          <span>本地统计 · 费用估算</span>
        </div>
        <div class="usage-periods">
          <div>
            <span>今日</span>
            <strong>{{ formatTokens(deepseekUsage.today.total_tokens) }}</strong>
            <small>{{ formatCost(deepseekUsage.today.estimated_cost_usd) }}</small>
          </div>
          <div>
            <span>本月</span>
            <strong>{{ formatTokens(deepseekUsage.month.total_tokens) }}</strong>
            <small>{{ formatCost(deepseekUsage.month.estimated_cost_usd) }}</small>
          </div>
          <div>
            <span>本地累计</span>
            <strong>{{ formatTokens(deepseekUsage.all_time.total_tokens) }}</strong>
            <small>{{ formatCost(deepseekUsage.all_time.estimated_cost_usd) }}</small>
          </div>
        </div>
        <div class="usage-breakdown">
          <span>命中 {{ formatTokens(deepseekUsage.all_time.cache_hit_tokens) }}</span>
          <span>未命中 {{ formatTokens(deepseekUsage.all_time.cache_miss_tokens) }}</span>
          <span>输出 {{ formatTokens(deepseekUsage.all_time.completion_tokens) }}</span>
        </div>
        <p>仅统计本机从启用此功能后发起的 DeepSeek 规划与汇总；金额按本地单价估算，不是官方账单。</p>
      </div>
    </section>
  </aside>
</template>
