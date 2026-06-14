<script setup lang="ts">
import { computed } from 'vue'

export interface LinePoint {
  label: string
  value: number
}

const props = withDefaults(
  defineProps<{ points: LinePoint[]; width?: number; height?: number; color?: string }>(),
  { width: 480, height: 180, color: '#f59e0b' },
)

const pad = { t: 16, r: 16, b: 32, l: 40 }
const innerW = computed(() => props.width - pad.l - pad.r)
const innerH = computed(() => props.height - pad.t - pad.b)
const hasData = computed(() => props.points.length > 0)

const maxVal = computed(() => Math.max(1, ...props.points.map((p) => p.value)))

const coords = computed(() => {
  const n = props.points.length
  if (!n) return []
  return props.points.map((p, i) => {
    const x = pad.l + (n === 1 ? innerW.value / 2 : (i / (n - 1)) * innerW.value)
    const y = pad.t + innerH.value - (p.value / maxVal.value) * innerH.value
    return { x, y, ...p }
  })
})

const polyline = computed(() => coords.value.map((c) => `${c.x},${c.y}`).join(' '))
const areaPath = computed(() => {
  const pts = coords.value
  if (!pts.length) return ''
  const first = pts[0]
  const last = pts[pts.length - 1]
  const base = pad.t + innerH.value
  return `M ${first.x} ${base} L ${pts.map((p) => `${p.x} ${p.y}`).join(' L ')} L ${last.x} ${base} Z`
})
</script>

<template>
  <div class="line-chart">
    <svg v-if="hasData" :width="width" :height="height" role="img" aria-label="折线图" class="line-svg">
      <line
        v-for="i in 4"
        :key="'g' + i"
        :x1="pad.l"
        :x2="width - pad.r"
        :y1="pad.t + ((i - 1) / 3) * innerH"
        :y2="pad.t + ((i - 1) / 3) * innerH"
        stroke="#e2e8f0"
        stroke-width="1"
      />
      <path :d="areaPath" :fill="color" fill-opacity="0.12" />
      <polyline
        :points="polyline"
        fill="none"
        :stroke="color"
        stroke-width="2.5"
        stroke-linejoin="round"
        stroke-linecap="round"
      />
      <circle v-for="(c, i) in coords" :key="i" :cx="c.x" :cy="c.y" r="4" :fill="color" stroke="#fff" stroke-width="2" />
      <text
        v-for="(c, i) in coords"
        :key="'lbl' + i"
        :x="c.x"
        :y="height - 8"
        text-anchor="middle"
        font-size="10"
        fill="#6b7280"
      >
        {{ c.label.slice(5) }}
      </text>
    </svg>
    <div v-else class="line-empty">
      <p class="line-empty-text">暂无好评趋势数据</p>
      <p class="line-empty-hint">近周期内无 4–5 星评价记录</p>
    </div>
  </div>
</template>

<style scoped>
.line-chart {
  width: 100%;
  min-height: 180px;
  overflow-x: auto;
}
.line-svg {
  display: block;
  max-width: 100%;
  height: auto;
}
.line-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  padding: 24px;
  text-align: center;
  background: #f9fafb;
  border-radius: 12px;
  border: 1px dashed #e5e7eb;
}
.line-empty-text {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #4b5563;
}
.line-empty-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: #9ca3af;
}
</style>
