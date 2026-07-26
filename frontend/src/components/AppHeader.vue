<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useTheme } from '../composables/useTheme'
import { useWorkspace } from '../composables/useWorkspace'
import type { Project } from '../types'
import { Sunny, Moon } from '@element-plus/icons-vue'
import ProjectDialog from './ProjectDialog.vue'

const router = useRouter()
const route = useRoute()
const { current, toggle } = useTheme()
const workspace = useWorkspace()

const showProjectDialog = ref(false)

// 本地 ref 仅用于 ElSelect 的 v-model
// 单向同步：workspace.state.projectId → projectId
const projectId = ref('')
watch(() => workspace.state.projectId, (id) => { projectId.value = id })

const projects = ref<Project[]>([])
watch(() => workspace.state.projects, (list) => { projects.value = list })

function handleSelect(val: string) {
  if (!val) return
  if (val === '__new__') {
    // 立即重置为当前项目 ID，避免 ElSelect 显示 "+ 新建项目"
    projectId.value = workspace.state.projectId
    showProjectDialog.value = true
    return
  }
  workspace.switchProject(val)
}

function onProjectCreated(p: Project) {
  showProjectDialog.value = false
  workspace.addProject(p)
}

function onDialogClosed() {
  showProjectDialog.value = false
  workspace.loadProjects()
}

onMounted(() => {
  workspace.loadProjects()
})
</script>

<template>
  <div class="app-header-row">
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

    <ElSelect
      v-model="projectId"
      size="small"
      class="header-project-select"
      placeholder="选择项目"
      @change="handleSelect"
    >
      <ElOption
        v-for="p in projects"
        :key="p.id"
        :value="p.id"
        :label="p.name"
      />
      <ElOption value="__new__" label="+ 新建项目" />
    </ElSelect>
  </div>

  <ProjectDialog
    v-if="showProjectDialog"
    :projects="projects"
    @created="onProjectCreated"
    @updated="workspace.loadProjects()"
    @close="onDialogClosed"
  />
</template>

<style scoped>
.app-header-row {
  display: flex;
  align-items: center;
  border-bottom: 1px solid var(--el-border-color-light);
}
.app-header {
  flex: 1;
  padding: 0 12px;
  border-bottom: none !important;
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
.header-project-select {
  width: 180px;
  flex-shrink: 0;
  margin-right: 12px;
}
</style>
