<script setup lang="ts">
/**
 * FlowYamlEditor — YAML 流程编辑器。
 * 左侧文本编辑 + 右侧校验反馈 + 保存/更新。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import type { FlowDefinition } from '../types'

const props = defineProps<{ flowName?: string }>()
const emit = defineEmits<{ saved: [name: string] }>()

const yamlContent = ref('')
const name = ref('')
const loading = ref(false)
const validateResult = ref<{ valid: boolean; errors: string[]; name?: string } | null>(null)
const isNew = ref(!props.flowName)

// Load existing flow
onMounted(async () => {
  if (props.flowName) {
    loading.value = true
    try {
      const flow = await api.flow(props.flowName)
      name.value = flow.name
      // Reconstruct YAML from flow definition
      yamlContent.value = toYaml(flow)
      isNew.value = false
    } catch (e: any) {
      ElMessage.error('加载流程失败: ' + (e?.message || '未知错误'))
    } finally {
      loading.value = false
    }
  }
})

// ---- Helpers ----
function toYaml(flow: FlowDefinition): string {
  const lines: string[] = []
  lines.push(`name: ${flow.name}`)
  if (flow.description) lines.push(`description: "${flow.description}"`)
  lines.push(`version: "${flow.version || '1.1'}"`)
  if (flow.keywords?.length) lines.push(`keywords: [${flow.keywords.join(', ')}]`)
  lines.push('')
  lines.push('nodes:')
  for (const n of flow.nodes) {
    lines.push(`  - id: ${n.id}`)
    lines.push(`    agent: ${n.agent}`)
    lines.push(`    title: "${n.title}"`)
    lines.push(`    objective: |`)
    lines.push(`      ${(n.objective || '').replace(/\n/g, '\n      ')}`)
    if (n.depends_on?.length) lines.push(`    depends_on: [${n.depends_on.join(', ')}]`)
  }
  // @ts-ignore — extended fields
  if (flow.conditions?.length) {
    lines.push('')
    lines.push('conditions:')
    for (const c of flow.conditions as any[]) {
      lines.push(`  - id: ${c.id}`)
      lines.push(`    condition: "${c.condition}"`)
      lines.push(`    then_branch: ${c.then_branch}`)
      if (c.else_branch) lines.push(`    else_branch: ${c.else_branch}`)
    }
  }
  // @ts-ignore
  if (flow.parallels?.length) {
    lines.push('')
    lines.push('parallels:')
    for (const p of flow.parallels as any[]) {
      lines.push(`  - id: ${p.id}`)
      lines.push(`    items: [${p.items.join(', ')}]`)
      if (p.max_concurrency) lines.push(`    max_concurrency: ${p.max_concurrency}`)
    }
  }
  // @ts-ignore
  if (flow.loops?.length) {
    lines.push('')
    lines.push('loops:')
    for (const l of flow.loops as any[]) {
      lines.push(`  - id: ${l.id}`)
      lines.push(`    condition: "${l.condition}"`)
      lines.push(`    body: ${l.body}`)
      lines.push(`    max_iterations: ${l.max_iterations || 10}`)
    }
  }
  // @ts-ignore
  if (flow.steps?.length) {
    lines.push('')
    lines.push(`steps: [${(flow.steps as string[]).join(', ')}]`)
  }
  return lines.join('\n')
}

async function doValidate() {
  if (!yamlContent.value.trim()) {
    validateResult.value = { valid: false, errors: ['YAML 内容不能为空'] }
    return
  }
  validateResult.value = await api.validateFlow(yamlContent.value)
}

async function doSave() {
  loading.value = true
  try {
    if (isNew.value) {
      await api.createFlow(name.value || 'untitled', yamlContent.value)
      ElMessage.success('流程创建成功')
    } else {
      await api.updateFlow(name.value, yamlContent.value)
      ElMessage.success('流程更新成功')
    }
    emit('saved', name.value)
    isNew.value = false
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e?.message || '未知错误'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flow-editor">
    <div class="editor-toolbar">
      <input
        v-model="name"
        placeholder="流程名称 (唯一)"
        class="name-input"
        :disabled="!isNew"
      />
      <span class="spacer" />
      <button class="tb-btn" @click="doValidate">校验</button>
      <button class="tb-btn primary" :disabled="loading" @click="doSave">
        {{ loading ? '保存中...' : '保存' }}
      </button>
    </div>

    <div class="editor-body">
      <div class="editor-pane">
        <textarea
          v-model="yamlContent"
          class="yaml-textarea"
          placeholder="# 在此编写 YAML 流程定义..."
          spellcheck="false"
        />
      </div>

      <div v-if="validateResult" class="validate-pane">
        <div class="vp-header">
          <span :class="validateResult.valid ? 'vp-ok' : 'vp-fail'">
            {{ validateResult.valid ? '✅ 校验通过' : '❌ 校验失败' }}
          </span>
        </div>
        <ul v-if="!validateResult.valid" class="vp-errors">
          <li v-for="(e, i) in validateResult.errors" :key="i">{{ e }}</li>
        </ul>
        <div v-else class="vp-hint">YAML 语法正确，可以保存。</div>
      </div>

      <div v-else class="validate-pane-empty">
        <span class="vp-hint">点击「校验」检查 YAML 语法</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.flow-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
}
.editor-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
.name-input {
  width: 200px;
  padding: 4px 8px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 4px;
  font-size: 13px;
  background: var(--bg-primary, #fff);
  color: var(--text-primary, #333);
}
.name-input:disabled { opacity: 0.6; }
.spacer { flex: 1; }
.tb-btn {
  font-size: 12px;
  padding: 4px 14px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 4px;
  background: var(--bg-secondary, #fefefe);
  cursor: pointer;
}
.tb-btn.primary {
  background: var(--brand, #409eff);
  color: #fff;
  border-color: var(--brand, #409eff);
}
.tb-btn:disabled { opacity: 0.5; cursor: default; }

.editor-body {
  flex: 1;
  display: grid;
  grid-template-columns: 3fr 1fr;
  gap: 8px;
  min-height: 0;
}

.editor-pane {
  overflow: hidden;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 6px;
}
.yaml-textarea {
  width: 100%;
  height: 100%;
  padding: 12px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 13px;
  line-height: 1.5;
  tab-size: 2;
  border: none;
  resize: none;
  background: var(--bg-primary, #fff);
  color: var(--text-primary, #333);
}

.validate-pane, .validate-pane-empty {
  border: 1px solid var(--border-color, #ddd);
  border-radius: 6px;
  padding: 12px;
  overflow-y: auto;
  font-size: 12px;
}
.vp-header { margin-bottom: 8px; font-weight: 600; }
.vp-ok { color: #67c23a; }
.vp-fail { color: #f56c6c; }
.vp-errors { margin: 0; padding-left: 18px; color: #f56c6c; }
.vp-errors li { margin-bottom: 4px; }
.vp-hint { color: var(--text-muted, #888); }
</style>
