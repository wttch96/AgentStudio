<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '../api/client'
import type { AgentTemplate, Project, ProjectAgent } from '../types'

const emit = defineEmits<{ created: [project: Project]; close: [] }>()
const props = defineProps<{ projects: Project[] }>()

const view = ref<'list' | 'create' | 'detail'>('list')
const name = ref(''); const projectName = ref(''); const rootDir = ref(''); const description = ref('')
const message = ref(''); const loading = ref(false)

const allTemplates = ref<AgentTemplate[]>([])
const selectedTemplates = ref<Set<string>>(new Set())

const dirPath = ref(''); const dirs = ref<{ name: string; path: string }[]>([])
const dirParent = ref<string | null>(null); const dirCurrent = ref('')

const detailProject = ref<Project | null>(null)
const detailAgents = ref<ProjectAgent[]>([])

const addAgentSelectVal = ref('')

async function browseDir(path?: string) {
  try {
    const target = path || rootDir.value || undefined
    const data = await api.browseWorkspace(target)
    dirs.value = data.directories; dirParent.value = data.parent
    dirCurrent.value = data.current; dirPath.value = data.current
    rootDir.value = data.current
  } catch (e) { console.warn('browseDir failed:', e) }
}

async function pickLocalFolder() {
  try {
    const data = await api.pickFolder()
    rootDir.value = data.path; await browseDir(data.path)
  } catch (e: any) {
    if (e.name === 'AbortError') return
    pickLocalFolderLegacy()
  }
}

function pickLocalFolderLegacy() {
  const input = document.createElement('input')
  input.type = 'file'; input.webkitdirectory = true
  input.onchange = async () => {
    if (input.files && input.files.length > 0) {
      const dirName = input.files[0].webkitRelativePath.split('/')[0]
      rootDir.value = dirName; await browseDir(dirName)
    }
  }
  input.click()
}

function selectDir(path: string) { rootDir.value = path; dirPath.value = path }

function toggleTemplate(id: string) {
  const next = new Set(selectedTemplates.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  selectedTemplates.value = next
}

async function createProject() {
  if (!name.value.trim() || !rootDir.value) return
  loading.value = true; message.value = ''
  try {
    const project = await api.createProject(
      name.value.trim(), rootDir.value, description.value,
      projectName.value.trim() || undefined,
    )
    for (const tid of [...selectedTemplates.value]) {
      await api.addProjectAgent(project.id, { template_id: tid })
    }
    message.value = '项目已创建'; emit('created', project)
  } catch (e) { message.value = e instanceof Error ? e.message : '创建失败' }
  finally { loading.value = false }
}

async function openDetail(p: Project) {
  detailProject.value = p
  try { detailAgents.value = (await api.projectAgents(p.id)).items } catch { detailAgents.value = [] }
  view.value = 'detail'
}

async function deleteProject() {
  if (!detailProject.value || !confirm(`确定删除项目 "${detailProject.value.name}"？`)) return
  try {
    await api.deleteProject(detailProject.value.id)
    detailProject.value = null; view.value = 'list'; emit('close')
  } catch (e) { message.value = e instanceof Error ? e.message : '删除失败' }
}

async function addAgentToProject(templateId: string) {
  if (!detailProject.value) return
  try {
    await api.addProjectAgent(detailProject.value.id, { template_id: templateId })
    detailAgents.value = (await api.projectAgents(detailProject.value.id)).items
  } catch (e) { message.value = e instanceof Error ? e.message : '添加失败' }
}

function onAddAgentSelect(val: string) {
  if (val) { addAgentToProject(val); addAgentSelectVal.value = '' }
}

async function removeAgent(agentId: string) {
  if (!detailProject.value) return
  try {
    await api.deleteProjectAgent(detailProject.value.id, agentId)
    detailAgents.value = (await api.projectAgents(detailProject.value.id)).items
  } catch (e) { message.value = e instanceof Error ? e.message : '删除失败' }
}

watch(() => props.projects.length, (n) => { if (n === 0) view.value = 'create' })
onMounted(async () => {
  browseDir()
  try { allTemplates.value = (await api.templates()).items.filter(t => t.agent_type !== 'brain') } catch { /* */ }
  if (props.projects.length === 0) view.value = 'create'
})
</script>

<template>
  <ElDialog :model-value="true" width="800px" @close="$emit('close')">
    <template #header>项目管理</template>

    <!-- Tab navigation -->
    <div class="border-bottom mb-3">
      <ElButton link size="small" class="me-1" :class="{ 'fw-bold': view === 'list' }" :disabled="!projects.length" @click="view = 'list'">项目列表</ElButton>
      <ElButton link size="small" class="me-1" :class="{ 'fw-bold': view === 'create' }" @click="view = 'create'">新建项目</ElButton>
      <ElButton v-if="detailProject" link size="small" class="me-1" :class="{ 'fw-bold': view === 'detail' }" @click="view = 'detail'">{{ detailProject.name }}</ElButton>
    </div>

    <!-- List view -->
    <template v-if="view === 'list' && projects.length">
      <div>
        <div v-for="p in projects" :key="p.id" class="d-flex justify-content-between align-items-center border-bottom p-2">
          <div @click="emit('created', p)" style="cursor:pointer" class="flex-grow-1">
            <strong>{{ p.name }}</strong>
            <small class="d-block text-secondary">{{ p.root_dir }}</small>
          </div>
          <ElButton size="small" @click="openDetail(p)">管理</ElButton>
        </div>
      </div>
    </template>

    <!-- Create view -->
    <template v-if="view === 'create'">
      <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" closable class="mb-2" @close="message = ''">
        <template #title>{{ message }}</template>
      </ElAlert>

      <div class="mb-2">
        <label class="form-label small">项目名称</label>
        <ElInput v-model="name" size="small" placeholder="例如：电商平台" @keyup.enter="createProject" />
      </div>
      <div class="mb-2">
        <label class="form-label small">项目标识 <span class="text-secondary">（数据目录名）</span></label>
        <ElInput v-model="projectName" size="small" placeholder="例如 ecommerce-platform；留空自动生成" />
        <small class="text-secondary">项目数据将保存到 .workspace/&lt;项目标识&gt;/</small>
      </div>

      <div class="mb-2">
        <label class="form-label small">项目根目录</label>
        <div class="d-flex gap-1">
          <ElInput v-model="rootDir" size="small" placeholder="输入本地文件夹路径，例如 /Users/wttch/Desktop" @keyup.enter="browseDir(rootDir)" class="flex-grow-1" />
          <ElButton size="small" @click="pickLocalFolder">选择文件夹</ElButton>
        </div>
      </div>

      <div class="mb-2 border rounded overflow-hidden">
        <div class="d-flex align-items-center gap-2 p-1 bg-body-tertiary border-bottom">
          <ElButton v-if="dirParent" size="small" link class="p-0" @click="browseDir(dirParent!)">&#8592; 上级目录</ElButton>
          <small class="text-secondary text-truncate">{{ dirCurrent }}</small>
        </div>
        <div style="max-height:140px;overflow-y:auto">
          <div v-for="d in dirs" :key="d.path" class="py-1 px-2 small border-bottom"
            :class="{ 'bg-body-secondary': rootDir === d.path }"
            style="cursor:pointer"
            @dblclick="browseDir(d.path)" @click="selectDir(d.path)">
            &#128193; {{ d.name }}
          </div>
          <div v-if="!dirs.length" class="text-secondary small text-center py-1">无子文件夹</div>
        </div>
      </div>

      <div class="mb-2 border rounded p-2">
        <div class="form-label small fw-semibold">选择 Agent 模板（可多选）</div>
        <div v-for="t in allTemplates" :key="t.id || t.name" class="mb-1">
          <ElCheckbox :model-value="selectedTemplates.has(t.id || t.name)" @change="() => toggleTemplate(t.id || t.name)">
            <strong>{{ t.display_name }}</strong>
            <small class="d-block text-secondary">{{ t.description }}</small>
          </ElCheckbox>
        </div>
      </div>

      <div class="mb-2">
        <label class="form-label small">描述（可选）</label>
        <ElInput v-model="description" size="small" placeholder="简要描述" />
      </div>

      <div class="d-flex justify-content-end gap-2 mt-3">
        <ElButton v-if="projects.length" size="small" @click="$emit('close')">取消</ElButton>
        <ElButton type="primary" size="small" :disabled="loading || !name || !rootDir" @click="createProject">
          {{ loading ? '创建中…' : '创建项目' }}
        </ElButton>
      </div>
    </template>

    <!-- Detail view -->
    <template v-if="view === 'detail' && detailProject">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <h6 class="mb-0">{{ detailProject.name }}</h6>
        <ElButton type="danger" size="small" @click="deleteProject">删除项目</ElButton>
      </div>
      <div class="text-secondary small mb-3">
        <div>根目录：{{ detailProject.root_dir }}</div>
        <div v-if="detailProject.description">描述：{{ detailProject.description }}</div>
      </div>

      <div class="mb-2">
        <strong class="small">项目 Agent（{{ detailAgents.filter(a => a.agent_type !== 'brain').length }} 个）</strong>
      </div>
      <div class="mb-2">
        <div v-for="a in detailAgents.filter(a => a.agent_type !== 'brain')" :key="a.id"
          class="d-flex justify-content-between align-items-center py-1 px-2 border-bottom">
          <div>
            <strong class="small">{{ a.display_name }}</strong>
            <small class="d-block text-secondary">{{ a.name }} · 子目录: {{ a.sub_dir || '根目录' }}</small>
          </div>
          <ElButton type="danger" size="small" plain @click="removeAgent(a.id)">移除</ElButton>
        </div>
      </div>

      <ElSelect v-model="addAgentSelectVal" size="small" @change="onAddAgentSelect" clearable placeholder="+ 添加 Agent…" class="mb-2">
        <ElOption v-for="t in allTemplates" :key="t.id || t.name" :value="t.id || t.name" :label="t.display_name" />
      </ElSelect>
      <ElAlert v-if="message" :type="message.includes('失败') ? 'error' : 'success'" closable class="mt-2" @close="message = ''">
        <template #title>{{ message }}</template>
      </ElAlert>
    </template>
  </ElDialog>
</template>
