<script setup lang="ts">
import { computed } from 'vue'

export interface PieSlice {
  label: string
  value: number
}

const props = defineProps<{ items: PieSlice[]; size?: number }>()
const size = computed(() => props.size ?? 200)
const colors = ['#f59e0b', '#3b82f6', '#10b981', '#8b5cf6', '#ef4444', '#06b6d4', '#ec4899', '#64748b']

const total = computed(() => props.items.reduce((s, i) => s + i.value, 0))
const hasData = computed(() => props.items.length > 0 && total.value > 0)

const slices = computed(() => {
  const t = total.value
  if (!t) return []
  let angle = -Math.PI / 2
  const cx = size.value / 2
  const cy = size.value / 2
  const outerR = size.value / 2 - 4
  const innerR = outerR * 0.55
  return props.items.map((item, idx) => {
    const frac = item.value / t
    const start = angle
    angle += frac * Math.PI * 2
    const end = angle
    const large = frac > 0.5 ? 1 : 0
    const x1o = cx + outerR * Math.cos(start)
    const y1o = cy + outerR * Math.sin(start)
    const x2o = cx + outerR * Math.cos(end)
    const y2o = cy + outerR * Math.sin(end)
    const x1i = cx + innerR * Math.cos(end)
    const y1i = cy + innerR * Math.sin(end)
    const x2i = cx + innerR * Math.cos(start)
    const y2i = cy + innerR * Math.sin(start)
    const d = [
      `M ${x1o} ${y1o}`,
      `A ${outerR} ${outerR} 0 ${large} 1 ${x2o} ${y2o}`,
      `L ${x1i} ${y1i}`,
      `A ${innerR} ${innerR} 0 ${large} 0 ${x2i} ${y2i}`,
      'Z',
    ].join(' ')
    return { d, color: colors[idx % colors.length], label: item.label, value: item.value, pct: Math.round(frac * 100) }
  })
})
</script>

<template>
  <div class="pie-wrap">
    <template v-if="hasData">
      <svg :width="size" :height="size" class="pie-svg" role="img" aria-label="意图分布环形图">
        <path v-for="(s, i) in slices" :key="i" :d="s.d" :fill="s.color" stroke="#fff" stroke-width="2" />
        <text :x="size / 2" :y="size / 2 - 4" text-anchor="middle" font-size="18" font-weight="800" fill="#1f2937">{{ total }}</text>
        <text :x="size / 2" :y="size / 2 + 14" text-anchor="middle" font-size="10" fill="#6b7280">条反馈</text>
      </svg>
      <ul class="pie-legend">
        <li v-for="(s, i) in slices" :key="'lg-' + i">
          <span class="dot" :style="{ background: s.color }" />
          <span class="lbl">{{ s.label }}</span>
          <span class="val">{{ s.value }} · {{ s.pct }}%</span>
        </li>
      </ul>
    </template>
    <div v-else class="pie-empty">
      <p class="pie-empty-text">暂无反馈数据</p>
      <p class="pie-empty-hint">用户点赞/点踩后会在此展示意图分布</p>
    </div>
  </div>
</template>

<style scoped>
.pie-wrap {
  min-height: 200px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px;
}
.pie-svg {
  flex-shrink: 0;
}
.pie-legend {
  list-style: none;
  margin: 0;
  padding: 0;
  flex: 1;
  min-width: 160px;
  display: grid;
  gap: 10px;
  font-size: 13px;
}
.pie-legend li {
  display: grid;
  grid-template-columns: 10px 1fr auto;
  gap: 8px;
  align-items: center;
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.lbl {
  color: #111827;
  font-weight: 600;
}
.val {
  color: #6b7280;
  font-variant-numeric: tabular-nums;
  font-size: 12px;
}
.pie-empty {
  width: 100%;
  padding: 32px 16px;
  text-align: center;
}
.pie-empty-text {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #4b5563;
}
.pie-empty-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: #9ca3af;
}
</style>
