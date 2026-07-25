<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { useTheme } from '../composables/useTheme'
import { Sunny, Moon } from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const { current, toggle } = useTheme()
</script>

<template>
  <ElMenu
    mode="horizontal"
    :default-active="route.path"
    :ellipsis="false"
    class="app-header"
    @select="(index: string) => { if (index) router.push(index) }"
  >
    <ElMenuItem index="/" class="brand-item">
      <span style="font-size:18px">&#129302;</span>
      <span style="font-weight:600;margin-left:6px">Agent Studio</span>
    </ElMenuItem>
    <ElMenuItem index="/">工作台</ElMenuItem>
    <ElMenuItem index="/config">配置中心</ElMenuItem>
    <ElMenuItem index="/flows">流程控制</ElMenuItem>
    <div class="flex-grow-1" />
    <ElMenuItem index="" style="border-bottom:none;cursor:default" @click="toggle">
      <ElIcon v-if="current === 'dark'" :size="16"><Sunny /></ElIcon>
      <ElIcon v-else :size="16"><Moon /></ElIcon>
      <span style="margin-left:4px">{{ current === 'dark' ? '浅色' : '深色' }}</span>
    </ElMenuItem>
  </ElMenu>
</template>

<style scoped>
.app-header {
  padding: 0 12px;
  border-bottom: 1px solid var(--el-border-color-light);
}
.brand-item {
  opacity: 1 !important;
}
.brand-item:hover {
  background: transparent !important;
}
.flex-grow-1 {
  flex-grow: 1;
}
</style>
