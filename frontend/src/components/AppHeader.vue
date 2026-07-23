<script setup lang="ts">
import { ref } from 'vue'
import type { SystemStatus } from '../types'
import { useTheme } from '../composables/useTheme'

defineProps<{
  status: SystemStatus | null
  leftPanelOpen: boolean
  rightPanelOpen: boolean
  projectName?: string
}>()
defineEmits<{ configure: []; toggleLeft: []; toggleRight: []; switchProject: [] }>()


const theme = useTheme()
const isDark = ref(theme.get() === 'dark')

function toggleTheme() {
  isDark.value = theme.toggle() === 'dark'
}
</script>

<template>
  <header class="app-header">
    <div class="brand-mark" aria-hidden="true">A</div>
    <div class="brand-copy">
      <strong>Agent Studio</strong>
      <span>DeepSeek × LangGraph × Claude</span>
    </div>
    <button
      class="panel-toggle"
      :class="{ active: leftPanelOpen }"
      type="button"
      :aria-pressed="leftPanelOpen"
      :title="leftPanelOpen ? '关闭任务侧栏' : '打开任务侧栏'"
      @click="$emit('toggleLeft')"
    >
      <span class="panel-icon left" aria-hidden="true" />
      <span class="sr-only">{{ leftPanelOpen ? '关闭' : '打开' }}任务侧栏</span>
    </button>
    <div class="header-spacer" />
    <button
      class="panel-toggle"
      :class="{ active: rightPanelOpen }"
      type="button"
      :aria-pressed="rightPanelOpen"
      :title="rightPanelOpen ? '关闭 Agent 状态栏' : '打开 Agent 状态栏'"
      @click="$emit('toggleRight')"
    >
      <span class="panel-icon right" aria-hidden="true" />
      <span class="sr-only">{{ rightPanelOpen ? '关闭' : '打开' }} Agent 状态栏</span>
    </button>
    <button class="theme-toggle" type="button" :title="isDark ? '切换到浅色模式' : '切换到深色模式'" @click="toggleTheme">
      {{ isDark ? '☀' : '☽' }}
    </button>
    <button class="header-action" type="button" @click="$emit('switchProject')">
      {{ projectName || '项目管理' }}
    </button>
    <button class="header-action" type="button" @click="$emit('configure')">配置中心</button>
    <div v-if="status" class="connection-chip" :class="{ demo: status.demo_mode }">
      <span class="status-dot" />
      {{ status.demo_mode ? '演示模式' : status.claude_route === 'cc-switch' ? 'CC Switch 已连接' : '模型已连接' }}
    </div>
    <div class="local-chip" title="服务仅监听本机回环地址">仅本机</div>
  </header>
</template>
