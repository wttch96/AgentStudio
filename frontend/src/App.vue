<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppHeader from './components/AppHeader.vue'
</script>

<template>
  <ElContainer class="app-root">
    <ElHeader class="app-header-bar">
      <AppHeader />
    </ElHeader>
    <ElMain class="app-main">
      <RouterView />
    </ElMain>
  </ElContainer>
</template>

<style scoped>
.app-root {
  height: 100vh;
  flex-direction: column;
}
.app-header-bar {
  padding: 0;
  height: auto;
}
.app-main {
  flex: 1;
  overflow: hidden;
  padding: 0;
}
</style>
