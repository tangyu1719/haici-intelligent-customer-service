<script setup lang="ts">
import { onMounted } from 'vue'
import { loadAuthFromStorage } from './api/auth'

onMounted(() => {
  loadAuthFromStorage()
})
</script>

<template>
  <div class="h-screen w-screen p-2 md:p-4 box-border bg-[#eef0f2]">
    <router-view v-slot="{ Component }">
      <keep-alive include="MainShell">
        <component :is="Component" />
      </keep-alive>
    </router-view>
  </div>
</template>
