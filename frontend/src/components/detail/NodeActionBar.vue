<script setup lang="ts">
const props = defineProps<{
  nodeId: string
  nodeName: string
  interruptible?: boolean
}>()

const emit = defineEmits<{
  interrupt: [nodeId: string]
}>()

function onInterrupt() {
  emit('interrupt', props.nodeId)
}
</script>

<template>
  <div class="action-bar">
    <ElButton
      text
      circle
      class="action-btn interrupt-btn"
      title="中止此节点任务"
      @click="onInterrupt"
    >
      <span class="action-btn-icon">■</span>
    </ElButton>
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
  background: rgba(240, 162, 69, 0.12);
  color: var(--orange);
  font-size: var(--ui-font-md);
  transition: background 0.15s;
}

.action-btn:hover {
  background: rgba(240, 162, 69, 0.22);
}

.action-btn-icon {
  line-height: 1;
}

</style>
