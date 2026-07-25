<script setup lang="ts">
defineProps<{
  nodeId: string
  x: number
  y: number
}>()
</script>

<template>
  <g :transform="`translate(${x}, ${y})`" class="error-overlay">
    <circle cx="0" cy="0" r="8" fill="var(--red)" />
    <text x="0" y="0" text-anchor="middle" dy="0.35em" fill="#fff" font-size="8" font-weight="700">!</text>
    <title>执行错误 - 点击查看详情</title>
  </g>
</template>

<style scoped>
.error-overlay {
  cursor: pointer;
}

.error-overlay circle {
  animation: error-blink 1s step-end infinite;
}

@keyframes error-blink {
  50% { opacity: 0.6; }
}
</style>
