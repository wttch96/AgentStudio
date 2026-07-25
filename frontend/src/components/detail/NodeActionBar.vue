<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  nodeId: string
  nodeName: string
  interruptible?: boolean
}>()

const emit = defineEmits<{
  interrupt: [nodeId: string]
  inject: [nodeId: string, instruction: string]
}>()

const showMenu = ref(false)
const showInjectInput = ref(false)
const instruction = ref('')

function onInterrupt() {
  emit('interrupt', props.nodeId)
  showMenu.value = false
}

function onInject() {
  if (instruction.value.trim()) {
    emit('inject', props.nodeId, instruction.value.trim())
    instruction.value = ''
    showInjectInput.value = false
    showMenu.value = false
  }
}

function toggleMenu() {
  showMenu.value = !showMenu.value
  showInjectInput.value = false
}

function closeMenu() {
  showMenu.value = false
  showInjectInput.value = false
}
</script>

<template>
  <div class="action-bar" @mouseleave="closeMenu">
    <!-- 中断按钮 -->
    <button
      type="button"
      class="action-btn interrupt-btn"
      title="中断此 Agent"
      @click="toggleMenu"
    >
      <span class="action-btn-icon">⏸</span>
    </button>

    <!-- 下拉菜单 -->
    <div v-if="showMenu" class="action-menu">
      <button type="button" class="action-menu-item" @click="onInterrupt">
        <span>⏸</span> 暂停 {{ nodeName }}
      </button>
      <button type="button" class="action-menu-item" @click="showInjectInput = true">
        <span>💉</span> 注入指令到 {{ nodeName }}
      </button>

      <!-- 注入指令输入 -->
      <div v-if="showInjectInput" class="inject-input-area">
        <textarea
          v-model="instruction"
          class="inject-textarea"
          placeholder="输入引导指令…"
          rows="2"
        />
        <div class="inject-actions">
          <button type="button" class="inject-cancel" @click="showInjectInput = false">取消</button>
          <button
            type="button"
            class="inject-submit"
            :disabled="!instruction.trim()"
            @click="onInject"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.action-bar {
  position: relative;
}

.action-btn {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 6px;
  background: rgba(240, 162, 69, 0.12);
  color: var(--orange);
  font-size: 0.625rem;
  cursor: pointer;
  transition: background 0.15s;
}

.action-btn:hover {
  background: rgba(240, 162, 69, 0.22);
}

.action-btn-icon {
  line-height: 1;
}

/* 下拉菜单 */
.action-menu {
  position: absolute;
  top: 100%;
  right: 0;
  z-index: 20;
  margin-top: 4px;
  min-width: 180px;
  padding: 4px;
  border-radius: 10px;
  background: rgba(44, 44, 46, 0.98);
  border: 1px solid var(--separator);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(24px);
}

.action-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--label);
  font-size: 0.5625rem;
  cursor: pointer;
  text-align: left;
}

.action-menu-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.action-menu-item span {
  font-size: 0.625rem;
}

/* 注入指令输入 */
.inject-input-area {
  padding: 6px 4px 4px;
  border-top: 1px solid var(--separator-soft);
  margin-top: 4px;
}

.inject-textarea {
  width: 100%;
  resize: vertical;
  border: 1px solid var(--separator-soft);
  border-radius: 6px;
  padding: 6px 8px;
  background: rgba(0, 0, 0, 0.2);
  color: var(--label);
  font: 0.5rem / 1.4 ui-monospace, 'SFMono-Regular', Menlo, monospace;
  outline: none;
}

.inject-textarea:focus {
  border-color: rgba(10, 132, 255, 0.5);
}

.inject-textarea::placeholder {
  color: var(--tertiary);
}

.inject-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  margin-top: 4px;
}

.inject-cancel,
.inject-submit {
  padding: 3px 8px;
  border: 0;
  border-radius: 5px;
  font-size: 0.5rem;
  cursor: pointer;
}

.inject-cancel {
  background: rgba(118, 118, 128, 0.12);
  color: var(--secondary);
}

.inject-cancel:hover {
  background: rgba(118, 118, 128, 0.22);
}

.inject-submit {
  background: rgba(10, 132, 255, 0.15);
  color: #64d2ff;
}

.inject-submit:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.25);
}

.inject-submit:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
