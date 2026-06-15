<script setup lang="ts">
defineProps<{
  value?: string
  maxHeight?: string
}>()
</script>

<template>
  <div class="log-scroll-detail">
    <textarea
      class="log-scroll-text"
      :value="value || ''"
      placeholder="（无内容）"
      readonly
      :style="{ maxHeight: maxHeight || '240px' }"
    />
  </div>
</template>

<style scoped>
.log-scroll-detail {
  width: 100%;
}

.log-scroll-text {
  width: 100%;
  min-height: 80px;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  color: #334155;
  resize: vertical;
  outline: none;
}
</style>
