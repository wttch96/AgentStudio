<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../../api/client'
import type { KnowledgeEntry, KnowledgeStats } from '../../types'

const props = defineProps<{ projectId: string }>()
const query = ref('')
const category = ref('')
const items = ref<KnowledgeEntry[]>([])
const stats = reactive<KnowledgeStats>({ total: 0, by_category: {}, expired: 0, relations: 0 })
const message = ref('')
const loading = ref(false)

// Edit/create form
const showForm = ref(false)
const editing = reactive({ id: '', title: '', content: '', category: 'general', tags: '', expires_at: '' })

// Import file
const showImport = ref(false)
const importCategory = ref('general')
const importPath = ref('')
const importing = ref(false)
const importResult = ref<{ imported: number; total_blocks: number; source: string } | null>(null)
const dirs = ref<{ name: string; path: string }[]>([])
const files = ref<{ name: string; path: string }[]>([])
const currentDir = ref('')

async function search() {
  loading.value = true
  message.value = ''
  try {
    if (query.value.trim()) {
      items.value = (await api.knowledgeSearch(query.value.trim(), category.value || undefined, undefined, props.projectId)).items
    } else {
      items.value = (await api.knowledgeSearch('', undefined, undefined, props.projectId)).items
    }
  } catch (e) {
    message.value = e instanceof Error ? e.message : '搜索失败'
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try { Object.assign(stats, await api.knowledgeStats(props.projectId)) } catch { /* ignore */ }
}

async function saveEntry() {
  const payload = {
    title: editing.title,
    content: editing.content,
    category: editing.category || 'general',
    tags: editing.tags.split(',').map((s: string) => s.trim()).filter(Boolean),
    expires_at: editing.expires_at || null,
  }
  try {
    if (editing.id) {
      await api.knowledgeUpdate(editing.id, payload)
      message.value = '知识已更新'
    } else {
      await api.knowledgeCreate(payload)
      message.value = '知识已创建'
    }
    showForm.value = false
    await search()
    await loadStats()
  } catch (e) {
    message.value = e instanceof Error ? e.message : '保存失败'
  }
}

async function deleteEntry(id: string) {
  if (!confirm('确定删除该知识条目？')) return
  try {
    await api.knowledgeDelete(id)
    message.value = '已删除'
    await search()
    await loadStats()
  } catch (e) {
    message.value = e instanceof Error ? e.message : '删除失败'
  }
}

async function feedback(id: string, type: 'up' | 'down') {
  try {
    await api.knowledgeFeedback(id, type)
    await search()
  } catch { /* ignore */ }
}

function startEdit(entry?: KnowledgeEntry) {
  if (entry) {
    Object.assign(editing, {
      id: entry.id, title: entry.title, content: entry.content,
      category: entry.category, tags: (entry.tags || []).join(', '),
      expires_at: entry.expires_at || '',
    })
  } else {
    Object.assign(editing, { id: '', title: '', content: '', category: 'general', tags: '', expires_at: '' })
  }
  showForm.value = true
}

// ── 文件导入 ──

async function openImport() {
  importResult.value = null
  importPath.value = ''
  currentDir.value = ''
  showImport.value = true
  await browseDir('')
}

async function browseDir(dir: string) {
  try {
    const result = await api.browseWorkspace(dir || undefined)
    dirs.value = result.directories
    files.value = result.files || []
    currentDir.value = result.current
  } catch {
    dirs.value = []
    files.value = []
  }
}

function selectFile(name: string) {
  const base = currentDir.value ? currentDir.value + '/' : ''
  importPath.value = base + name
}

function parentDir() {
  if (!currentDir.value) return
  const parts = currentDir.value.split('/')
  parts.pop()
  browseDir(parts.join('/'))
}

async function doImport() {
  if (!importPath.value.trim()) return
  importing.value = true
  message.value = ''
  try {
    importResult.value = await api.knowledgeImport(importPath.value.trim(), importCategory.value, props.projectId)
    message.value = `成功导入 ${importResult.value.imported} 条知识`
    showImport.value = false
    await search()
    await loadStats()
  } catch (e) {
    message.value = e instanceof Error ? e.message : '导入失败'
  } finally {
    importing.value = false
  }
}

onMounted(() => { search(); loadStats() })
</script>

<template>
  <div class="knowledge-panel">
    <!-- Search -->
    <div class="knowledge-search">
      <input v-model="query" type="text" placeholder="搜索知识库…" @keyup.enter="search" />
      <select v-model="category" @change="search">
        <option value="">全部分类</option>
        <option v-for="(_, cat) in stats.by_category" :key="cat" :value="cat">{{ cat }}</option>
      </select>
      <button type="button" @click="search" :disabled="loading">{{ loading ? '搜索中…' : '搜索' }}</button>
      <button type="button" class="add-btn" @click="startEdit()">+ 新增</button>
      <button type="button" class="import-btn" @click="openImport">📄 导入文件</button>
    </div>

    <!-- Stats -->
    <div class="knowledge-stats">
      <span>共 {{ stats.total }} 条知识</span>
      <span v-if="stats.expired > 0" class="expired-warn">{{ stats.expired }} 条已过期</span>
      <span>{{ stats.relations }} 个关联</span>
    </div>

    <!-- Message -->
    <div v-if="message" :class="{ error: message.includes('失败') }" class="msg">{{ message }}</div>

    <!-- Entry list -->
    <div class="knowledge-list">
      <article v-for="item in items" :key="item.id" class="k-entry">
        <div class="k-entry-header">
          <strong>{{ item.title }}</strong>
          <span class="k-source-type" :class="'st-' + (item.source_type || 'manual')">
            {{ item.source_type === 'auto' ? '🤖 自学' : item.source_type === 'import' ? '📄 导入' : '✍️ 手动' }}
          </span>
          <span class="k-category">{{ item.category }}</span>
          <span class="k-score">{{ item.score.toFixed(0) }}%</span>
        </div>
        <p class="k-content">{{ item.content.slice(0, 200) }}{{ item.content.length > 200 ? '…' : '' }}</p>
        <div class="k-meta">
          <span v-if="item.tags.length">{{ item.tags.join(', ') }}</span>
          <span v-if="item.expires_at" class="k-expiry">过期: {{ item.expires_at }}</span>
        </div>
        <div class="k-actions">
          <button @click="feedback(item.id, 'up')" title="有用">&#x1F44D;</button>
          <button @click="feedback(item.id, 'down')" title="无用">&#x1F44E;</button>
          <button @click="startEdit(item)">编辑</button>
          <button class="danger" @click="deleteEntry(item.id)">删除</button>
        </div>
      </article>
    </div>

    <!-- Edit form -->
    <div v-if="showForm" class="k-form-overlay" @click.self="showForm = false">
      <div class="k-form">
        <h3>{{ editing.id ? '编辑知识' : '新增知识' }}</h3>
        <label>标题 <input v-model="editing.title" type="text" /></label>
        <label>分类
          <select v-model="editing.category">
            <option value="general">通用</option>
            <option value="api">API</option>
            <option value="code">代码示例</option>
            <option value="naming">命名规范</option>
            <option value="error">错误处理</option>
            <option value="deployment">部署</option>
          </select>
        </label>
        <label>标签（逗号分隔）<input v-model="editing.tags" type="text" placeholder="vue, typescript, api" /></label>
        <label>过期时间 <input v-model="editing.expires_at" type="datetime-local" /></label>
        <label>内容 <textarea v-model="editing.content" rows="8" /></label>
        <div class="k-form-actions">
          <button @click="saveEntry">保存</button>
          <button class="cancel" @click="showForm = false">取消</button>
        </div>
      </div>
    </div>

    <!-- Import file dialog -->
    <div v-if="showImport" class="k-form-overlay" @click.self="showImport = false">
      <div class="k-form import-dialog">
        <h3>📄 从文件导入知识</h3>
        <p class="import-hint">选择 .md / .txt 文件，Markdown 将按 ## 标题自动拆分为多条知识。</p>

        <label>分类
          <select v-model="importCategory">
            <option value="general">通用</option>
            <option value="api">API</option>
            <option value="code">代码示例</option>
            <option value="naming">命名规范</option>
            <option value="error">错误处理</option>
            <option value="deployment">部署</option>
          </select>
        </label>

        <!-- Path display -->
        <div class="import-path-row">
          <label>文件路径</label>
          <div class="path-input-row">
            <input v-model="importPath" type="text" placeholder="选择文件或直接输入路径…" />
            <button v-if="currentDir" type="button" class="dir-up" @click="parentDir">⬆ 上级</button>
          </div>
        </div>

        <!-- Directory browser -->
        <div class="dir-browser">
          <div v-if="currentDir" class="dir-current">📁 {{ currentDir || '/' }}</div>
          <div v-if="dirs.length === 0 && files.length === 0 && !currentDir" class="dir-empty">加载中…</div>
          <div class="dir-list">
            <button
              v-for="d in dirs"
              :key="d.path"
              type="button"
              class="dir-entry"
              @click="selectFile(d.name); browseDir(d.path)"
            >
              <span class="dir-icon">📁</span>
              <span>{{ d.name }}</span>
            </button>
            <button
              v-for="f in files"
              :key="f.path"
              type="button"
              class="dir-entry file-entry"
              @click="importPath = f.path"
            >
              <span class="dir-icon">📄</span>
              <span>{{ f.name }}</span>
            </button>
          </div>
          <div v-if="dirs.length === 0 && files.length === 0 && currentDir" class="dir-empty">此目录为空。请选择其他目录，或直接在路径框输入文件路径。</div>
        </div>

        <div class="k-form-actions">
          <button @click="doImport" :disabled="!importPath.trim() || importing">
            {{ importing ? '导入中…' : '导入' }}
          </button>
          <button class="cancel" @click="showImport = false">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.knowledge-panel { padding: 0.5rem 0; }
.knowledge-search { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
.knowledge-search input { flex: 1; min-width: 120px; padding: 0.4rem 0.6rem; border: 1px solid var(--separator-soft); border-radius: 6px; background: var(--surface); color: var(--label); font-size: 0.8rem; }
.knowledge-search select { padding: 0.4rem; border: 1px solid var(--separator-soft); border-radius: 6px; background: var(--surface); color: var(--label); font-size: 0.8rem; }
.knowledge-search button { padding: 0.4rem 0.8rem; border: 0; border-radius: 6px; color: #fff; cursor: pointer; font-size: 0.8rem; white-space: nowrap; }
.knowledge-search button:not(.add-btn):not(.import-btn) { background: var(--blue); }
.knowledge-search button:disabled { opacity: 0.5; }
.add-btn { background: var(--green) !important; }
.import-btn { background: rgba(191, 90, 242, 0.7) !important; }
.import-btn:hover { background: rgba(191, 90, 242, 0.9) !important; }

.knowledge-stats { display: flex; gap: 1rem; font-size: 0.7rem; color: var(--secondary); margin-bottom: 0.5rem; }
.expired-warn { color: var(--orange); }

.msg { font-size: 0.75rem; margin-bottom: 0.5rem; color: var(--green); }
.msg.error { color: var(--red); }

.knowledge-list { display: flex; flex-direction: column; gap: 0.5rem; max-height: 500px; overflow-y: auto; }
.k-entry { padding: 0.6rem; border: 1px solid var(--separator-soft); border-radius: 8px; background: var(--surface); }
.k-entry-header { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.3rem; }
.k-entry-header strong { font-size: 0.8rem; }
.k-category { font-size: 0.6rem; background: var(--blue-soft); color: var(--blue); padding: 0.1rem 0.4rem; border-radius: 4px; }
.k-source-type { font-size: 0.6rem; padding: 0.1rem 0.4rem; border-radius: 4px; }
.st-manual { background: rgba(100, 210, 140, 0.15); color: var(--green); }
.st-import { background: rgba(191, 90, 242, 0.12); color: rgba(191, 90, 242, 1); }
.st-auto { background: rgba(255, 159, 10, 0.12); color: var(--orange); }
.k-score { font-size: 0.65rem; color: var(--secondary); margin-left: auto; }
.k-content { font-size: 0.72rem; color: var(--secondary); margin: 0.25rem 0; line-height: 1.4; }
.k-meta { font-size: 0.6rem; color: var(--tertiary); margin-bottom: 0.3rem; }
.k-expiry { color: var(--orange); margin-left: 0.5rem; }
.k-actions { display: flex; gap: 0.3rem; }
.k-actions button { padding: 0.15rem 0.4rem; border: 1px solid var(--separator-soft); border-radius: 4px; background: var(--surface); color: var(--secondary); cursor: pointer; font-size: 0.65rem; }
.k-actions button:hover { background: var(--surface-hover); }
.k-actions .danger { color: var(--red); border-color: rgba(255,69,58,.3); }

.k-form-overlay { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; background: rgba(0,0,0,.5); }
.k-form { width: 500px; max-height: 80vh; overflow-y: auto; padding: 1.25rem; background: var(--bg); border-radius: 12px; display: flex; flex-direction: column; gap: 0.6rem; }
.k-form h3 { margin: 0; font-size: 1rem; }
.k-form label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.7rem; color: var(--secondary); }
.k-form input, .k-form select, .k-form textarea { padding: 0.35rem; border: 1px solid var(--separator-soft); border-radius: 6px; background: var(--surface); color: var(--label); font-size: 0.8rem; }
.k-form-actions { display: flex; gap: 0.5rem; justify-content: flex-end; }
.k-form-actions button { padding: 0.4rem 0.8rem; border: 0; border-radius: 6px; background: var(--blue); color: #fff; cursor: pointer; }
.k-form-actions .cancel { background: var(--surface-hover); color: var(--label); }

/* Import dialog */
.import-dialog { width: 550px; }
.import-hint { font-size: 0.72rem; color: var(--secondary); margin: 0; }
.import-path-row label { font-size: 0.65rem; color: var(--secondary); }
.path-input-row { display: flex; gap: 0.4rem; }
.path-input-row input { flex: 1; }
.dir-up { padding: 0.3rem 0.6rem; border: 1px solid var(--separator-soft); border-radius: 6px; background: var(--surface); color: var(--secondary); cursor: pointer; font-size: 0.7rem; }
.dir-browser { max-height: 250px; overflow-y: auto; border: 1px solid var(--separator-soft); border-radius: 8px; padding: 0.5rem; background: var(--surface); }
.dir-current { font-size: 0.7rem; color: var(--blue); margin-bottom: 0.35rem; font-weight: 600; }
.dir-list { display: flex; flex-direction: column; gap: 2px; }
.dir-entry { display: flex; align-items: center; gap: 0.4rem; width: 100%; padding: 0.35rem 0.5rem; border: 0; border-radius: 5px; background: transparent; color: var(--label); cursor: pointer; font-size: 0.75rem; text-align: left; }
.dir-entry:hover { background: var(--surface-hover); }
.file-entry { color: var(--secondary); }
.file-entry:hover { background: rgba(191, 90, 242, 0.12); color: rgba(191, 90, 242, 1); }
.dir-icon { font-size: 0.9rem; }
.dir-empty { font-size: 0.65rem; color: var(--tertiary); padding: 0.5rem; text-align: center; }
</style>
