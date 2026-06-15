<script setup lang="ts">
import { ref } from 'vue'
import LogContentZoomModal from './LogContentZoomModal.vue'

const props = withDefaults(
  defineProps<{
    value?: string
    maxHeight?: string
    title?: string
    zoomable?: boolean
  }>(),
  { zoomable: true },
)

const zoomOpen = ref(false)

function openZoom(): void {
  if (props.zoomable === false) return
  zoomOpen.value = true
}
</script>

<template>
  <div
    class="log-scroll-detail"
    :class="{ 'log-scroll-detail--zoomable': zoomable !== false }"
    :title="zoomable !== false ? '点击放大查看' : undefined"
    @click="openZoom"
  >
    <textarea
      class="log-scroll-text"
      :value="value || ''"
      placeholder="（无内容）"
      readonly
      tabindex="-1"
      :style="{ maxHeight: maxHeight || '240px' }"
    />
    <span v-if="zoomable !== false" class="log-scroll-hint">点击放大</span>
  </div>

  <LogContentZoomModal
    :open="zoomOpen"
    :title="title"
    :value="value"
    mono
    @close="zoomOpen = false"
  />
</template>

<style scoped>
.log-scroll-detail {
  position: relative;
  width: 100%;
}

.log-scroll-detail--zoomable {
  cursor: zoom-in;
}

.log-scroll-detail--zoomable:hover .log-scroll-text {
  border-color: #94a3b8;
  background: #f1f5f9;
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
  pointer-events: none;
}

.log-scroll-hint {
  position: absolute;
  right: 8px;
  bottom: 8px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #e2e8f0;
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.15s;
}

.log-scroll-detail--zoomable:hover .log-scroll-hint {
  opacity: 1;
}
</style>
