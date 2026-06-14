<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  page: number
  size: number
  total: number
}>()

const emit = defineEmits<{
  'update:page': [number]
  'update:size': [number]
}>()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.size)))
const rangeText = computed(() => {
  if (!props.total) return '0 条'
  const start = (props.page - 1) * props.size + 1
  const end = Math.min(props.page * props.size, props.total)
  return `${start}-${end} / 共 ${props.total} 条`
})

const go = (p: number): void => {
  const next = Math.min(Math.max(1, p), totalPages.value)
  emit('update:page', next)
}

const onSize = (e: Event): void => {
  emit('update:size', Number((e.target as HTMLSelectElement).value))
  emit('update:page', 1)
}
</script>

<template>
  <div class="list-pagination">
    <span class="lp-range">{{ rangeText }}</span>
    <label class="lp-size">
      每页
      <select :value="size" @change="onSize">
        <option :value="10">10</option>
        <option :value="20">20</option>
        <option :value="50">50</option>
        <option :value="100">100</option>
      </select>
    </label>
    <div class="lp-btns">
      <button type="button" :disabled="page <= 1" @click="go(1)">首页</button>
      <button type="button" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
      <span class="lp-page">{{ page }} / {{ totalPages }}</span>
      <button type="button" :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
      <button type="button" :disabled="page >= totalPages" @click="go(totalPages)">末页</button>
    </div>
  </div>
</template>

<style scoped>
.list-pagination {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
  padding: 10px 12px;
  border-top: 1px solid rgba(54, 62, 66, 0.08);
  font-size: 11px;
  color: #64748b;
}
.lp-range {
  font-weight: 700;
  color: #363e42;
}
.lp-size select {
  margin-left: 4px;
  border-radius: 6px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  padding: 2px 6px;
}
.lp-btns {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}
.lp-btns button {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  background: #fff;
  cursor: pointer;
}
.lp-btns button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.lp-page {
  font-weight: 700;
  color: #363e42;
  min-width: 56px;
  text-align: center;
}
</style>
