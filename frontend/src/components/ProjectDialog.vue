<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '../api/client'
import type { AgentTemplate, Project, ProjectAgent } from '../types'

const emit = defineEmits<{
  created: [project: Project]
  close: []
}>()

const props = defineProps<{ projects: Project[] }>()

// Steps: 'list' | 'create' | 'detail'
const view = ref<'list' | 'create' | 'detail'>('list')
const name = ref('')
const rootDir = ref('')
const description = ref('')
const message = ref('')
const loading = ref(false)

// Templates for checkbox selection (claude only, no brain/rag)
const allTemplates = ref<AgentTemplate[]>([])
const selectedTemplates = ref<Set<string>>(new Set())

// Directory browser
const dirPath = ref('')
const dirs = ref<{ name: string; path: string }[]>([])
const dirParent = ref<string | null>(null)
const dirCurrent = ref('')

// Detail view
const detailProject = ref<Project | null>(null)
const detailAgents = ref<ProjectAgent[]>([])

async function browseDir(path?: string) {
  try {
    const data = await api.browseWorkspace(path)
    dirs.value = data.directories
    dirParent.value = data.parent
    dirCurrent.value = data.current
    dirPath.value = data.current
  } catch { /* */ }
}

function selectDir(path: string) { rootDir.value = path; dirPath.value = path }

function toggleTemplate(id: string) {
  const next = new Set(selectedTemplates.value)
  if (next.has(id)) { next.delete(id) } else { next.add(id) }
  selectedTemplates.value = next
}

async function createProject() {
  if (!name.value.trim() || !rootDir.value) return
  loading.value = true; message.value = ''
  try {
    const tids = [...selectedTemplates.value]
    const project = await api.createProject(name.value.trim(), rootDir.value, description.value)
    // Add selected agents
    for (const tid of tids) {
      await api.addProjectAgent(project.id, tid)
    }
    message.value = '项目已创建'
    emit('created', project)
  } catch (e) {
    message.value = e instanceof Error ? e.message : '创建失败'
  } finally { loading.value = false }
}

async function openDetail(p: Project) {
  detailProject.value = p
  try { detailAgents.value = (await api.projectAgents(p.id)).items } catch { detailAgents.value = [] }
  view.value = 'detail'
}

async function deleteProject() {
  if (!detailProject.value || !confirm('确定删除项目 "' + detailProject.value.name + '"？此操作不可恢复。')) return
  try {
    await api.deleteProject(detailProject.value.id)
    detailProject.value = null
    view.value = 'list'
    emit('close')
  } catch (e) { message.value = e instanceof Error ? e.message : '删除失败' }
}

async function addAgentToProject(templateId: string) {
  if (!detailProject.value) return
  try {
    await api.addProjectAgent(detailProject.value.id, templateId)
    detailAgents.value = (await api.projectAgents(detailProject.value.id)).items
  } catch (e) { message.value = e instanceof Error ? e.message : '添加失败' }
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
  <div class="pm-overlay" @click.self="$emit('close')">
    <div class="pm-dialog">
      <!-- Tabs -->
      <div class="pm-tabs">
        <button :class="{ active: view === 'list' }" @click="view = 'list'" :disabled="!projects.length">项目列表</button>
        <button :class="{ active: view === 'create' }" @click="view = 'create'">新建项目</button>
        <button v-if="detailProject" :class="{ active: view === 'detail' }" @click="view = 'detail'">
          {{ detailProject.name }}
        </button>
      </div>

      <!-- VIEW: List -->
      <template v-if="view === 'list' && projects.length">
        <div class="pm-list">
          <div v-for="p in projects" :key="p.id" class="pm-item">
            <div class="pm-item-info" @click="$emit('created', p)">
              <strong>{{ p.name }}</strong>
              <small>{{ p.root_dir }}</small>
              <small v-if="p.description" class="pm-item-desc">{{ p.description }}</small>
            </div>
            <button class="pm-btn-small" @click="openDetail(p)">管理</button>
          </div>
        </div>
      </template>

      <!-- VIEW: Create -->
      <template v-if="view === 'create'">
        <div v-if="message" :class="{ error: message.includes('失败') }" class="pm-msg">{{ message }}</div>

        <label>项目名称
          <input v-model="name" placeholder="例如：电商平台" @keyup.enter="createProject" />
        </label>

        <label>项目根目录
          <div class="pm-dir-input">
            <input v-model="rootDir" placeholder="选择或输入目录" />
            <button type="button" @click="browseDir(dirPath)">浏览</button>
          </div>
        </label>

        <div class="pm-browser">
          <div class="pm-browser-bar">
            <button v-if="dirParent" @click="browseDir(dirParent!)">&#x2190;</button>
            <span class="pm-browser-path">{{ dirCurrent }}</span>
          </div>
          <div class="pm-browser-list">
            <div v-for="d in dirs" :key="d.path" class="pm-browser-item"
              :class="{ selected: rootDir === d.path }"
              @dblclick="browseDir(d.path)" @click="selectDir(d.path)">
              <span>&#x1F4C1;</span> {{ d.name }}
            </div>
            <div v-if="!dirs.length" class="pm-empty">无子文件夹</div>
          </div>
        </div>

        <!-- Agent template checkboxes -->
        <div class="pm-templates">
          <div class="pm-templates-title">选择 Agent 模板（可多选，后续也可添加）</div>
          <label v-for="t in allTemplates" :key="t.id" class="pm-check">
            <input type="checkbox" :checked="selectedTemplates.has(t.id)" @change="toggleTemplate(t.id)" />
            <span>
              <strong>{{ t.display_name }}</strong>
              <small>{{ t.description }}</small>
            </span>
          </label>
        </div>

        <label>描述（可选）<input v-model="description" placeholder="简要描述" /></label>

        <div class="pm-actions">
          <button class="pm-btn primary" :disabled="loading || !name || !rootDir" @click="createProject">
            {{ loading ? '创建中…' : '创建项目' }}
          </button>
          <button v-if="projects.length" class="pm-btn" @click="$emit('close')">取消</button>
        </div>
      </template>

      <!-- VIEW: Detail -->
      <template v-if="view === 'detail' && detailProject">
        <div class="pm-detail">
          <div class="pm-detail-header">
            <h3>{{ detailProject.name }}</h3>
            <button class="pm-btn danger" @click="deleteProject">删除项目</button>
          </div>
          <div class="pm-detail-meta">
            <span>根目录：{{ detailProject.root_dir }}</span>
            <span v-if="detailProject.description">描述：{{ detailProject.description }}</span>
          </div>

          <div class="pm-section">
            <div class="pm-section-header">
              <strong>项目 Agent（{{ detailAgents.filter(a => a.agent_type !== 'brain').length }} 个）</strong>
            </div>
            <div class="pm-agent-list">
              <div v-for="a in detailAgents.filter(a => a.agent_type !== 'brain')" :key="a.id" class="pm-agent-item">
                <div>
                  <strong>{{ a.display_name }}</strong>
                  <small>{{ a.name }} · 子目录: {{ a.sub_dir || '根目录' }}</small>
                </div>
                <button class="pm-btn-small danger" @click="removeAgent(a.id)">移除</button>
              </div>
            </div>

            <!-- Add more agents -->
            <div class="pm-add-section">
              <select @change="addAgentToProject(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
                <option value="">+ 添加 Agent…</option>
                <option v-for="t in allTemplates" :key="t.id" :value="t.id">{{ t.display_name }}</option>
              </select>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.pm-overlay { position: fixed; inset: 0; z-index: 200; display: grid; place-items: center; background: rgba(0,0,0,.55); backdrop-filter: blur(4px); }
.pm-dialog { width: 560px; max-height: 85vh; overflow-y: auto; padding: 1.5rem; background: var(--bg); border-radius: 14px; display: flex; flex-direction: column; gap: 0.7rem; box-shadow: 0 20px 60px rgba(0,0,0,.4); }

.pm-tabs { display: flex; gap: 0; border-bottom: 1px solid var(--separator-soft); margin-bottom: 0.25rem; }
.pm-tabs button { flex: 1; padding: 0.45rem; border: 0; background: transparent; font-size: 0.8rem; font-weight: 600; cursor: pointer; color: var(--secondary); border-bottom: 2px solid transparent; }
.pm-tabs button.active { color: var(--label); border-bottom-color: var(--blue); }
.pm-tabs button:disabled { opacity: 0.4; cursor: default; }

.pm-list { display: flex; flex-direction: column; gap: 0.35rem; }
.pm-item { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0.6rem; border: 1px solid var(--separator-soft); border-radius: 8px; background: var(--surface); }
.pm-item-info { flex: 1; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
.pm-item-info:hover strong { color: var(--blue); }
.pm-item strong { font-size: 0.82rem; }
.pm-item small { font-size: 0.62rem; color: var(--secondary); }

.pm-msg { font-size: 0.8rem; color: var(--green); }
.pm-msg.error { color: var(--red); }

label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.72rem; color: var(--secondary); font-weight: 500; }
input, select { padding: 0.4rem 0.55rem; border: 1px solid var(--separator-soft); border-radius: 6px; background: var(--surface); color: var(--label); font-size: 0.82rem; }

.pm-dir-input { display: flex; gap: 0.3rem; }
.pm-dir-input input { flex: 1; }
.pm-dir-input button { padding: 0.35rem 0.6rem; border: 1px solid var(--separator-soft); border-radius: 6px; background: var(--surface); color: var(--blue); cursor: pointer; font-size: 0.78rem; }

.pm-browser { border: 1px solid var(--separator-soft); border-radius: 8px; overflow: hidden; }
.pm-browser-bar { display: flex; align-items: center; gap: 0.4rem; padding: 0.3rem 0.45rem; background: var(--surface); border-bottom: 1px solid var(--separator-soft); }
.pm-browser-bar button { padding: 0.1rem 0.35rem; border: 0; background: var(--surface-hover); color: var(--label); cursor: pointer; border-radius: 4px; font-size: 0.75rem; }
.pm-browser-path { font-size: 0.6rem; color: var(--secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pm-browser-list { max-height: 140px; overflow-y: auto; }
.pm-browser-item { display: flex; align-items: center; gap: 0.4rem; padding: 0.3rem 0.55rem; cursor: pointer; font-size: 0.75rem; }
.pm-browser-item:hover { background: var(--surface-hover); }
.pm-browser-item.selected { background: var(--blue-soft); color: var(--blue); }
.pm-empty { padding: 0.6rem; text-align: center; color: var(--tertiary); font-size: 0.7rem; }

.pm-templates { border: 1px solid var(--separator-soft); border-radius: 8px; padding: 0.5rem; }
.pm-templates-title { font-size: 0.72rem; font-weight: 600; margin-bottom: 0.4rem; color: var(--label); }
.pm-check { display: flex; align-items: flex-start; gap: 0.4rem; padding: 0.3rem 0; cursor: pointer; font-size: 0.75rem; }
.pm-check span { display: flex; flex-direction: column; gap: 1px; }
.pm-check strong { font-size: 0.78rem; color: var(--label); }
.pm-check small { font-size: 0.62rem; color: var(--secondary); }
.pm-item-desc { font-size: 0.58rem; color: var(--tertiary); font-style: italic; }

.pm-detail-header { display: flex; justify-content: space-between; align-items: center; }
.pm-detail-header h3 { margin: 0; font-size: 1rem; }
.pm-detail-meta { display: flex; flex-direction: column; gap: 3px; font-size: 0.7rem; color: var(--secondary); }

.pm-section { margin-top: 0.5rem; }
.pm-section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem; }
.pm-section-header strong { font-size: 0.82rem; }

.pm-agent-list { display: flex; flex-direction: column; gap: 0.25rem; }
.pm-agent-item { display: flex; justify-content: space-between; align-items: center; padding: 0.35rem 0.45rem; border: 1px solid var(--separator-soft); border-radius: 6px; background: var(--surface); }
.pm-agent-item div { display: flex; flex-direction: column; gap: 1px; }
.pm-agent-item strong { font-size: 0.75rem; }
.pm-agent-item small { font-size: 0.6rem; color: var(--secondary); }

.pm-add-section { margin-top: 0.4rem; }
.pm-add-section select { width: 100%; }

.pm-actions { display: flex; gap: 0.4rem; justify-content: flex-end; margin-top: 0.25rem; }
.pm-btn { padding: 0.45rem 0.9rem; border: 1px solid var(--separator-soft); border-radius: 8px; background: var(--surface); color: var(--label); cursor: pointer; font-size: 0.82rem; font-weight: 500; }
.pm-btn.primary { background: var(--blue); color: #fff; border-color: var(--blue); }
.pm-btn.danger { color: var(--red); border-color: rgba(255,69,58,.3); }
.pm-btn:disabled { opacity: 0.5; cursor: default; }
.pm-btn-small { padding: 0.2rem 0.4rem; border: 1px solid var(--separator-soft); border-radius: 5px; background: var(--surface); color: var(--secondary); cursor: pointer; font-size: 0.65rem; }
.pm-btn-small.danger { color: var(--red); }
</style>
