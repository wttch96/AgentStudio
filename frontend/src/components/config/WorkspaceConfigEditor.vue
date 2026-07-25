<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { FolderOpened } from '@element-plus/icons-vue'
import { api } from '../../api/client'

const emit = defineEmits<{ saved: [] }>()
const path = ref('')
const parent = ref<string | null>(null)
const directories = ref<{ name: string; path: string }[]>([])
const loading = ref(false)
const saving = ref(false)
const message = ref('')

async function browse(target?: string) {
  loading.value = true; message.value = ''
  try {
    const result = await api.browseWorkspace(target)
    path.value = result.current; parent.value = result.parent; directories.value = result.directories
  } catch (error) { message.value = error instanceof Error ? error.message : '目录读取失败' }
  finally { loading.value = false }
}

async function browseTypedPath() { await browse(path.value.trim()) }

async function save() {
  saving.value = true; message.value = ''
  try {
    const result = await api.updateWorkspace(path.value.trim())
    path.value = result.path
    message.value = '工作目录已保存。'; emit('saved')
  } catch (error) { message.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}

onMounted(() => browse())
</script>

<template>
  <ElCard>
    <template #header>
      <div class="d-flex align-items-center gap-2">
        <ElIcon size="20"><FolderOpened /></ElIcon>
        <div>
          <strong>默认工作根目录</strong>
          <p class="text-secondary mb-0">后端会记住此目录。所有新任务都以此作为 Claude Agent 的工作目录。</p>
        </div>
      </div>
    </template>

    <div class="mb-3">
      <label class="form-label">当前路径</label>
      <div class="d-flex gap-2">
        <ElInput v-model="path" size="small" autocomplete="off" @keydown.enter="browseTypedPath" class="flex-grow-1" />
        <ElButton size="small" :disabled="loading" @click="browseTypedPath">转到</ElButton>
      </div>
    </div>

    <div class="d-flex align-items-center gap-2 mb-3">
      <ElButton size="small" :disabled="!parent || loading" @click="browse(parent ?? undefined)">&#8249; 上一级</ElButton>
      <span class="text-secondary small">{{ loading ? '读取中…' : `${directories.length} 个子文件夹` }}</span>
    </div>

    <div class="mb-3 border rounded" style="max-height: 240px; overflow-y: auto;">
      <div v-for="d in directories" :key="d.path"
        class="py-1 px-2 d-flex align-items-center gap-2"
        :class="{ 'bg-primary bg-opacity-10': path === d.path }"
        style="cursor: pointer;"
        @dblclick="browse(d.path)" @click="path = d.path">
        <span class="text-secondary">&#9632;</span>
        <strong class="small">{{ d.name }}</strong>
        <small class="text-secondary ms-auto">{{ d.path }}</small>
      </div>
      <div v-if="!loading && directories.length === 0" class="py-1 px-2 text-secondary small">此目录没有可浏览的子文件夹。</div>
    </div>
    <p class="form-text mb-3">单击选择文件夹；双击进入文件夹继续浏览。</p>

    <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" :closable="false" class="mb-3">{{ message }}</ElAlert>
    <ElButton type="primary" size="small" :disabled="saving || loading" @click="save">{{ saving ? '保存中…' : '设为工作目录' }}</ElButton>
  </ElCard>
</template>
