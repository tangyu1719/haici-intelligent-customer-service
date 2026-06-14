<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'
import SimpleLineChart from './charts/SimpleLineChart.vue'

interface TypeMetrics {
  call_count: number
  success_count: number
  fail_count: number
  fail_rate: number
  avg_rtt_ms: number
  total_tokens: number
  avg_tokens: number
  recall_rate: number | null
  accuracy_rate: number | null
  avg_hits: number | null
}

interface EvalOverview {
  period_days: number
  generated_at: string
  summary: TypeMetrics
  by_type: Record<string, TypeMetrics>
  daily_trend: { date: string; call_count: number; fail_count: number; avg_rtt_ms: number }[]
  types: string[]
}

const TYPE_LABELS: Record<string, string> = {
  llm: 'LLM 调用',
  rag: 'RAG 检索',
  tool: '工具调用',
  mcp: 'MCP 调用',
  embedding: '向量嵌入',
}

const days = ref(7)
const loading = ref(false)
const data = ref<EvalOverview | null>(null)

const load = async (): Promise<void> => {
  loading.value = true
  try {
    const res = await fetch(`/api/v1/admin/eval/overview?days=${days.value}`, { headers: authHeaders() })
    if (res.ok) data.value = await res.json()
  } finally {
    loading.value = false
  }
}

const pct = (v: number | null | undefined): string => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)
const num = (v: number | null | undefined): string => (v == null ? '—' : String(v))

const trendPoints = computed(() =>
  (data.value?.daily_trend || []).map((d) => ({ label: d.date, value: d.call_count })),
)

onMounted(load)
</script>

<template>
  <div class="eval-page">
    <header class="eval-hero card">
      <div class="eval-hero-top">
        <div class="eval-hero-ic" aria-hidden="true">📊</div>
        <div>
          <h1 class="eval-title">EVAL 评测系统</h1>
          <p class="eval-lede">专链统计 Agent 调用：LLM、RAG（独立）、工具/MCP、嵌入；含召回率、准确率、Token、RTT、失败率。</p>
        </div>
      </div>
      <div class="eval-toolbar">
        <label>统计周期
          <select v-model.number="days" @change="load">
            <option :value="7">近 7 天</option>
            <option :value="14">近 14 天</option>
            <option :value="30">近 30 天</option>
          </select>
        </label>
        <button type="button" class="btn-refresh" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
      </div>
    </header>

    <section v-if="data" class="kpi-grid">
      <article class="kpi card kpi-total">
        <h3>汇总</h3>
        <dl>
          <div><dt>调用次数</dt><dd>{{ data.summary.call_count }}</dd></div>
          <div><dt>失败率</dt><dd>{{ pct(data.summary.fail_rate) }}</dd></div>
          <div><dt>平均 RTT</dt><dd>{{ num(data.summary.avg_rtt_ms) }} ms</dd></div>
          <div><dt>Token 消耗</dt><dd>{{ num(data.summary.total_tokens) }}</dd></div>
          <div><dt>准确率</dt><dd>{{ pct(data.summary.accuracy_rate) }}</dd></div>
          <div><dt>召回率</dt><dd>{{ pct(data.summary.recall_rate) }}</dd></div>
        </dl>
      </article>
      <article v-for="t in data.types" :key="t" class="kpi card">
        <h3>{{ TYPE_LABELS[t] || t }}</h3>
        <dl>
          <div><dt>调用次数</dt><dd>{{ data.by_type[t]?.call_count ?? 0 }}</dd></div>
          <div><dt>失败率</dt><dd>{{ pct(data.by_type[t]?.fail_rate) }}</dd></div>
          <div><dt>平均 RTT</dt><dd>{{ num(data.by_type[t]?.avg_rtt_ms) }} ms</dd></div>
          <div><dt>Token</dt><dd>{{ num(data.by_type[t]?.total_tokens) }}</dd></div>
          <div v-if="t === 'rag'"><dt>召回率</dt><dd>{{ pct(data.by_type[t]?.recall_rate) }}</dd></div>
          <div v-if="t === 'rag'"><dt>平均命中</dt><dd>{{ num(data.by_type[t]?.avg_hits) }}</dd></div>
          <div v-else><dt>准确率</dt><dd>{{ pct(data.by_type[t]?.accuracy_rate) }}</dd></div>
        </dl>
      </article>
    </section>

    <section class="card trend-card">
      <h3 class="section-title">每日调用趋势</h3>
      <SimpleLineChart :points="trendPoints" :width="720" color="#3b82f6" />
    </section>

    <p v-if="!loading && data && !data.summary.call_count" class="hint">
      暂无 Agent 专链调用记录。发起智能对话或 RAG 检索后将自动写入 EVAL 指标。
    </p>
  </div>
</template>

<style scoped>
.eval-page { max-width: 1200px; margin: 0 auto; display: grid; gap: 16px; }
.card { background: #fff; border: 1px solid rgba(54,62,66,.1); border-radius: 16px; }
.eval-hero { padding: 20px 22px; }
.eval-hero-top { display: flex; gap: 14px; align-items: flex-start; }
.eval-hero-ic { font-size: 28px; line-height: 1; }
.eval-title { margin: 0; font-size: 18px; font-weight: 800; }
.eval-lede { margin: 6px 0 0; font-size: 12px; color: #64748b; line-height: 1.55; max-width: 72ch; }
.eval-toolbar { display: flex; align-items: center; gap: 12px; margin-top: 14px; font-size: 11px; color: #64748b; }
.eval-toolbar select { margin-left: 6px; border: 1px solid rgba(54,62,66,.15); border-radius: 6px; padding: 4px 8px; }
.btn-refresh { font-size: 11px; font-weight: 700; color: #2563eb; background: rgba(37,99,235,.08); border: 1px solid rgba(37,99,235,.2); border-radius: 8px; padding: 5px 12px; cursor: pointer; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.kpi { padding: 14px 16px; }
.kpi-total { border-color: rgba(37,99,235,.25); background: linear-gradient(135deg, rgba(37,99,235,.04), #fff); }
.kpi h3 { margin: 0 0 10px; font-size: 12px; font-weight: 800; color: #334155; }
.kpi dl { margin: 0; display: grid; gap: 6px; }
.kpi dl > div { display: flex; justify-content: space-between; font-size: 11px; }
.kpi dt { color: #94a3b8; font-weight: 600; }
.kpi dd { margin: 0; font-weight: 800; font-variant-numeric: tabular-nums; color: #0f172a; }
.trend-card { padding: 16px 18px 20px; }
.section-title { margin: 0 0 12px; font-size: 13px; font-weight: 800; }
.hint { text-align: center; color: #94a3b8; font-size: 12px; padding: 8px; }
</style>
