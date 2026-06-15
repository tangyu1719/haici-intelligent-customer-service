<script setup lang="ts">
import { onUnmounted, watch } from 'vue'

const props = defineProps<{
  open: boolean
  title?: string
  value?: string
  mono?: boolean
}>()

const emit = defineEmits<{ close: [] }>()

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.open,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
  { immediate: true },
)

onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="log-zoom-mask" @click.self="emit('close')">
      <div class="log-zoom-panel" role="dialog" aria-modal="true" :aria-label="title || '内容详情'">
        <div class="log-zoom-hd">
          <h4>{{ title || '内容详情' }}</h4>
          <button type="button" class="log-zoom-close" title="关闭 (Esc)" @click="emit('close')">✕</button>
        </div>
        <div class="log-zoom-body">
          <textarea
            class="log-zoom-text"
            :class="{ mono }"
            :value="value || ''"
            placeholder="（无内容）"
            readonly
          />
        </div>
        <p class="log-zoom-tip">点击遮罩或按 Esc 关闭</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.log-zoom-mask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  background: rgba(15, 23, 42, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.log-zoom-panel {
  width: min(920px, 96vw);
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.22);
  border: 1px solid #e2e8f0;
}

.log-zoom-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.log-zoom-hd h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 800;
  color: #1e293b;
}

.log-zoom-close {
  border: none;
  background: #f1f5f9;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #64748b;
  flex-shrink: 0;
}

.log-zoom-close:hover {
  background: #e2e8f0;
}

.log-zoom-body {
  flex: 1;
  min-height: 0;
  padding: 16px 18px;
}

.log-zoom-text {
  width: 100%;
  height: min(68vh, 640px);
  box-sizing: border-box;
  padding: 14px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
  resize: none;
  outline: none;
}

.log-zoom-text.mono {
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
}

.log-zoom-tip {
  margin: 0;
  padding: 8px 18px 14px;
  text-align: center;
  font-size: 11px;
  color: #94a3b8;
  flex-shrink: 0;
}
</style>
