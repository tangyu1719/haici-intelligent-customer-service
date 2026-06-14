<script setup lang="ts">
import type { ListQueryState } from '../utils/listQuery'

const props = defineProps<{
  modelValue: ListQueryState
  sortOptions?: Array<{ value: string; label: string }>
  showId?: boolean
  showName?: boolean
  showKeyword?: boolean
  showDate?: boolean
  showSort?: boolean
  namePlaceholder?: string
  keywordPlaceholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [ListQueryState]
  search: []
  reset: []
}>()

const patch = (partial: Partial<ListQueryState>): void => {
  emit('update:modelValue', { ...props.modelValue, ...partial, page: 1 })
}

const onSearch = (): void => emit('search')
const onReset = (): void => emit('reset')
</script>

<template>
  <div class="list-query-bar">
    <div class="lq-grid">
      <label v-if="showId !== false" class="lq-field">
        <span>ID</span>
        <input
          :value="modelValue.id"
          type="text"
          inputmode="numeric"
          placeholder="精确 ID"
          @input="patch({ id: ($event.target as HTMLInputElement).value })"
          @keyup.enter="onSearch"
        />
      </label>
      <label v-if="showName !== false" class="lq-field">
        <span>名称</span>
        <input
          :value="modelValue.name"
          type="text"
          :placeholder="namePlaceholder || '名称模糊查询'"
          @input="patch({ name: ($event.target as HTMLInputElement).value })"
          @keyup.enter="onSearch"
        />
      </label>
      <label v-if="showKeyword !== false" class="lq-field lq-wide">
        <span>关键词</span>
        <input
          :value="modelValue.keyword"
          type="text"
          :placeholder="keywordPlaceholder || '近意/模糊查询'"
          @input="patch({ keyword: ($event.target as HTMLInputElement).value })"
          @keyup.enter="onSearch"
        />
      </label>
      <label v-if="showDate !== false" class="lq-field">
        <span>开始日期</span>
        <input
          :value="modelValue.dateFrom"
          type="date"
          @input="patch({ dateFrom: ($event.target as HTMLInputElement).value })"
        />
      </label>
      <label v-if="showDate !== false" class="lq-field">
        <span>结束日期</span>
        <input
          :value="modelValue.dateTo"
          type="date"
          @input="patch({ dateTo: ($event.target as HTMLInputElement).value })"
        />
      </label>
      <label v-if="showSort !== false && sortOptions?.length" class="lq-field">
        <span>排序</span>
        <select :value="modelValue.sortBy" @change="patch({ sortBy: ($event.target as HTMLSelectElement).value })">
          <option value="">默认</option>
          <option v-for="o in sortOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>
      <label v-if="showSort !== false" class="lq-field">
        <span>方向</span>
        <select :value="modelValue.sortOrder" @change="patch({ sortOrder: ($event.target as HTMLSelectElement).value as 'asc' | 'desc' })">
          <option value="desc">降序</option>
          <option value="asc">升序</option>
        </select>
      </label>
    </div>
    <div class="lq-actions">
      <button type="button" class="lq-btn primary" @click="onSearch">查询</button>
      <button type="button" class="lq-btn" @click="onReset">重置</button>
    </div>
  </div>
</template>

<style scoped>
.list-query-bar {
  padding: 12px;
  border-radius: 12px;
  border: 1px solid rgba(54, 62, 66, 0.1);
  background: #fcfcfc;
  margin-bottom: 12px;
}
.lq-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 8px 10px;
}
.lq-wide {
  grid-column: span 2;
}
.lq-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
}
.lq-field input,
.lq-field select {
  font-size: 12px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  border-radius: 8px;
  padding: 6px 8px;
  background: #fff;
}
.lq-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.lq-btn {
  font-size: 11px;
  font-weight: 700;
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  background: #fff;
  cursor: pointer;
}
.lq-btn.primary {
  background: #363e42;
  color: #fff;
  border-color: #363e42;
}
</style>
