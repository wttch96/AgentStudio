<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api/client'

const emit = defineEmits<{ saved: [] }>()
const path = ref('')
const parent = ref<string | null>(null)
const directories = ref<{ name: string; path: string }[]>([])
const loading = ref(false)
const saving = ref(false)
const message = ref('')

async function browse(target?: string) {
  loading.value = true
  message.value = ''
  try {
    const result = await api.browseWorkspace(target)
    path.value = result.current
    parent.value = result.parent
    directories.value = result.directories
  } catch (error) {
    message.value = error instanceof Error ? error.message : '目录读取失败'
  } finally {
    loading.value = false
  }
}

async function browseTypedPath() {
  await browse(path.value.trim())
}

async function save() {
  saving.value = true
  message.value = ''
  try {
    const result = await api.updateWorkspace(path.value.trim())
    path.value = result.path
    message.value = '工作目录已保存，之后创建的任务都会使用该目录。'
    emit('saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(() => browse())
</script>

<template>
  <div class="config-editor workspace-editor">
    <label class="field-label" for="workspace-path">默认工作根目录</label>
    <div class="path-entry">
      <input
        id="workspace-path"
        v-model="path"
        class="config-input"
        autocomplete="off"
        @keydown.enter="browseTypedPath"
      />
      <button type="button" :disabled="loading" @click="browseTypedPath">转到</button>
    </div>
    <p class="field-help">后端会记住此目录。所有新任务都以它作为 Claude Agent 的工作目录。</p>

    <div class="directory-toolbar">
      <button type="button" :disabled="!parent || loading" @click="browse(parent ?? undefined)">‹ 上一级</button>
      <span>{{ loading ? '正在读取…' : `${directories.length} 个子文件夹` }}</span>
    </div>
    <div class="directory-list">
      <button
        v-for="directory in directories"
        :key="directory.path"
        type="button"
        :class="{ selected: path === directory.path }"
        @dblclick="browse(directory.path)"
        @click="path = directory.path"
      >
        <span aria-hidden="true">▰</span>
        <strong>{{ directory.name }}</strong>
        <small>{{ directory.path }}</small>
      </button>
      <p v-if="!loading && directories.length === 0" class="config-empty">此目录没有可浏览的子文件夹。</p>
    </div>
    <p class="field-help">单击选择文件夹；双击进入文件夹继续浏览。</p>

    <div class="config-actions">
      <span :class="{ error: message.includes('失败') || message.includes('不存在') }">{{ message }}</span>
      <button type="button" :disabled="saving || loading" @click="save">{{ saving ? '保存中…' : '设为工作目录' }}</button>
    </div>
  </div>
</template>
