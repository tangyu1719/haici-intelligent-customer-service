<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'
import { renderMarkdown } from '../utils/renderMarkdown'
import SimpleLineChart from './charts/SimpleLineChart.vue'
import SimplePieChart from './charts/SimplePieChart.vue'
import FeedbackFlowChart from './charts/FeedbackFlowChart.vue'

interface FlowStage {
  id: string
  label: string
  count: number
  desc?: string
}

interface Persona {
  agent_id: string
  display_name: string
  role: string
  reply_style: string
  layers: { L0: string; L1: string; L2: string }
}

interface Analytics {
  period_days: number
  total_feedback: number
  intent_pie: { intent: string; label: string; count: number }[]
  intent_ratings: { intent: string; label: string; avg_rating: number; count: number; like_rate: number | null }[]
  failed_intent_rank: { intent: string; label: string; fail_count: number; total: number }[]
  corrected_intent_rank?: { label: string; count: number }[]
  positive_review_trend: { date: string; count: number }[]
  flow_pipeline?: { title?: string; stages: FlowStage[] }
  summary: { avg_rating: number; intent_like_rate: number | null }
  demo_mode?: boolean
  demo_note?: string
}

const days = ref(30)
const loading = ref(false)
const analytics = ref<Analytics | null>(null)
const persona = ref<Persona | null>(null)
const aiLoading = ref(false)
const aiMarkdown = ref('')
const aiPowered = ref(false)

const pieItems = computed(() =>
  (analytics.value?.intent_pie || []).map((i) => ({ label: i.label, value: i.count })),
)

const linePoints = computed(() =>
  (analytics.value?.positive_review_trend || []).map((d) => ({ label: d.date, value: d.count })),
)

const flowStages = computed(() => analytics.value?.flow_pipeline?.stages || [])
const flowTitle = computed(() => analytics.value?.flow_pipeline?.title || '用户反馈处理流程')

const loadAnalytics = async (): Promise<void> => {
  loading.value = true
  try {
    const res = await fetch(`/api/v1/admin/feedback/analytics?days=${days.value}`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      analytics.value = data
      if (data.persona_hint) persona.value = data.persona_hint
    }
  } finally {
    loading.value = false
  }
}

const loadPersona = async (): Promise<void> => {
  const res = await fetch('/api/v1/admin/feedback/persona', { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    persona.value = data.persona
  }
}

const runAiAnalysis = async (): Promise<void> => {
  aiLoading.value = true
  aiMarkdown.value = ''
  try {
    const res = await fetch(`/api/v1/admin/feedback/ai-analysis?days=${days.value}`, {
      method: 'POST',
      headers: authHeaders(),
    })
    if (res.ok) {
      const data = await res.json()
      aiMarkdown.value = data.analysis_markdown || ''
      aiPowered.value = !!data.llm_powered
      if (data.persona) persona.value = data.persona
    } else {
      aiMarkdown.value = '【分析失败】请稍后重试或检查 LLM 配置。'
    }
  } finally {
    aiLoading.value = false
  }
}

const analysisHtml = computed(() => (aiMarkdown.value ? renderMarkdown(aiMarkdown.value) : ''))

onMounted(async () => {
  await loadPersona()
  await loadAnalytics()
})
</script>

<template>
  <div class="fb-dash">
    <header class="dash-hero card">
      <div class="dash-hero-top">
        <div class="dash-hero-ic" aria-hidden="true">📈</div>
        <div>
          <h2 class="dash-title">用户反馈综合看板</h2>
          <p class="dash-lede">意图分布、评分、失败意图排行与用户好评趋势；底部由独立 AI 评测 Agent 生成全面分析。</p>
        </div>
      </div>
      <div class="dash-toolbar">
        <label>统计周期
          <select v-model.number="days" @change="loadAnalytics">
            <option :value="7">近 7 天</option>
            <option :value="30">近 30 天</option>
            <option :value="90">近 90 天</option>
          </select>
        </label>
        <button type="button" class="btn-refresh" :disabled="loading" @click="loadAnalytics">
          {{ loading ? '加载中…' : '刷新看板' }}
        </button>
      </div>
      <div v-if="analytics" class="summary-chips">
        <span v-if="analytics.demo_mode" class="chip chip-demo">演示数据</span>
        <span class="chip">反馈 {{ analytics.total_feedback }} 条</span>
        <span class="chip">均分 {{ analytics.summary.avg_rating || '—' }}</span>
        <span v-if="analytics.summary.intent_like_rate != null" class="chip">
          意图准确率 {{ (analytics.summary.intent_like_rate * 100).toFixed(0) }}%
        </span>
      </div>
      <p v-if="analytics?.demo_mode && analytics.demo_note" class="demo-note">{{ analytics.demo_note }}</p>
    </header>

    <section v-if="flowStages.length" class="card chart-card span-full">
      <FeedbackFlowChart :title="flowTitle" :stages="flowStages" />
    </section>

    <div class="charts-grid">
      <section class="card chart-card">
        <h3 class="section-title">意图维度 · 提问意图分布</h3>
        <SimplePieChart :items="pieItems" :size="180" />
      </section>

      <section class="card chart-card">
        <h3 class="section-title">意图维度 · 各意图平均评分</h3>
        <div v-if="analytics?.intent_ratings?.length" class="score-table-wrap">
          <table class="score-table">
            <thead>
              <tr><th>意图</th><th>均分</th><th>样本</th><th>点赞率</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in analytics.intent_ratings" :key="row.intent">
                <td>{{ row.label }}</td>
                <td><span class="stars">{{ '★'.repeat(Math.round(row.avg_rating)) }}</span> {{ row.avg_rating }}</td>
                <td>{{ row.count }}</td>
                <td>{{ row.like_rate != null ? `${(row.like_rate * 100).toFixed(0)}%` : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="chart-empty">
          <p class="chart-empty-title">暂无评分数据</p>
          <p class="chart-empty-hint">用户对助手回答点赞/点踩后，将按意图汇总均分</p>
        </div>
      </section>

      <section class="card chart-card">
        <h3 class="section-title">意图维度 · 失败意图排行（高→低）</h3>
        <ol v-if="analytics?.failed_intent_rank?.length" class="fail-rank">
          <li v-for="(row, idx) in analytics.failed_intent_rank" :key="row.intent">
            <span class="rank">{{ idx + 1 }}</span>
            <span class="name">{{ row.label }}</span>
            <span class="stat">{{ row.fail_count }} / {{ row.total }} 次踩</span>
          </li>
        </ol>
        <div v-else class="chart-empty">
          <p class="chart-empty-title">暂无失败意图记录</p>
          <p class="chart-empty-hint">当前周期内无点踩反馈，或尚未标注意图</p>
        </div>
      </section>

      <section v-if="analytics?.corrected_intent_rank?.length" class="card chart-card">
        <h3 class="section-title">意图纠偏 · 用户认为正确意图（高→低）</h3>
        <ol class="fail-rank corrected-rank">
          <li v-for="(row, idx) in analytics.corrected_intent_rank" :key="row.label">
            <span class="rank">{{ idx + 1 }}</span>
            <span class="name">{{ row.label }}</span>
            <span class="stat">{{ row.count }} 次</span>
          </li>
        </ol>
      </section>

      <section class="card chart-card span2">
        <h3 class="section-title">AI 回答维度 · 用户好评趋势（4–5 星/日）</h3>
        <SimpleLineChart :points="linePoints" :width="640" color="#f59e0b" />
      </section>
    </div>

    <!-- agpz 风格三栏：人设侧栏 + 分析主区 + 摘要 -->
    <section class="ai-agent-section">
      <header class="ai-section-hd">
        <h3>AI 智能分析</h3>
        <button type="button" class="btn-analyze" :disabled="aiLoading" @click="runAiAnalysis">
          {{ aiLoading ? '小析分析中…' : '生成 AI 分析报告' }}
        </button>
      </header>
      <div class="agpz-grid">
        <aside class="card agpz-side">
          <div class="agpz-side-h">
            <h4>评测 Agent 人设</h4>
            <p class="agpz-side-sub">独立分析师 · 数据驱动解读</p>
          </div>
          <div v-if="persona" class="persona-card">
            <div class="persona-avatar">{{ persona.display_name?.slice(0, 1) || '析' }}</div>
            <p class="persona-name">{{ persona.display_name }}</p>
            <p class="persona-role">{{ persona.role }}</p>
            <p class="persona-style">风格：{{ persona.reply_style }}</p>
          </div>
          <article v-if="persona" class="agpz-layer">
            <header class="agpz-layer-head"><span class="agpz-layer-tag">L0</span><span>个性层</span></header>
            <p class="layer-text">{{ persona.layers.L0 }}</p>
          </article>
          <article v-if="persona" class="agpz-layer">
            <header class="agpz-layer-head"><span class="agpz-layer-tag">L1</span><span>业务层</span></header>
            <p class="layer-text">{{ persona.layers.L1 }}</p>
          </article>
          <article v-if="persona" class="agpz-layer">
            <header class="agpz-layer-head"><span class="agpz-layer-tag">L2</span><span>约束层</span></header>
            <p class="layer-text">{{ persona.layers.L2 }}</p>
          </article>
        </aside>

        <main class="card agpz-main">
          <div class="agpz-editor-head">
            <h4>分析报告</h4>
            <span v-if="aiPowered" class="llm-badge">LLM 真实生成</span>
          </div>
          <div v-if="aiLoading" class="analysis-loading">小析正在阅读看板数据并撰写报告…</div>
          <div v-else-if="analysisHtml" class="analysis-body md-body" v-html="analysisHtml" />
          <p v-else class="analysis-placeholder">点击「生成 AI 分析报告」，小析将基于上方看板数据输出全面 Markdown 洞察与改进建议。</p>
        </main>

        <aside class="card agpz-hist">
          <h4>数据摘要</h4>
          <ul v-if="analytics" class="digest-list">
            <li v-for="item in analytics.intent_pie.slice(0, 5)" :key="item.intent">
              {{ item.label }}：{{ item.count }} 条
            </li>
            <li v-if="analytics.failed_intent_rank[0]">
              最高失败意图：{{ analytics.failed_intent_rank[0].label }}
            </li>
            <li>统计周期：近 {{ analytics.period_days }} 天</li>
          </ul>
        </aside>
      </div>
    </section>
  </div>
</template>

<style scoped>
.fb-dash { display: grid; gap: 16px; max-width: 1200px; margin: 0 auto; }
.card { background: #fff; border: 1px solid rgba(54,62,66,.1); border-radius: 16px; }
.dash-hero { padding: 18px 20px; }
.dash-hero-top { display: flex; gap: 12px; align-items: flex-start; }
.dash-hero-ic { font-size: 26px; }
.dash-title { margin: 0; font-size: 17px; font-weight: 800; }
.dash-lede { margin: 6px 0 0; font-size: 12px; color: #64748b; line-height: 1.5; }
.dash-toolbar { display: flex; gap: 12px; align-items: center; margin-top: 12px; font-size: 11px; color: #64748b; }
.dash-toolbar select { margin-left: 6px; border-radius: 6px; border: 1px solid rgba(54,62,66,.15); padding: 4px 8px; }
.btn-refresh { font-size: 11px; font-weight: 700; color: #d97706; background: rgba(217,119,6,.08); border: 1px solid rgba(217,119,6,.2); border-radius: 8px; padding: 5px 12px; cursor: pointer; }
.summary-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.chip { font-size: 13px; font-weight: 700; padding: 6px 12px; border-radius: 999px; background: #f3f4f6; color: #1f2937; border: 1px solid #d1d5db; }
.chip-demo { background: #fff7ed; color: #9a3412; border-color: #fdba74; }
.demo-note { margin: 10px 0 0; font-size: 12px; color: #92400e; line-height: 1.5; }
.charts-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.span-full { grid-column: 1 / -1; margin-bottom: 0; }
.chart-card { padding: 16px 18px 20px; min-height: 240px; display: flex; flex-direction: column; }
.span2 { grid-column: 1 / -1; }
.section-title { margin: 0 0 14px; font-size: 13px; font-weight: 800; color: #b45309; }
.score-table-wrap { overflow-x: auto; flex: 1; }
.score-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.score-table th { text-align: left; color: #6b7280; font-weight: 700; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; }
.score-table td { padding: 10px; border-bottom: 1px solid #f3f4f6; color: #111827; }
.stars { color: #f59e0b; }
.fail-rank { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; flex: 1; }
.fail-rank li { display: grid; grid-template-columns: 28px 1fr auto; align-items: center; font-size: 13px; padding: 10px 12px; background: #fef2f2; border-radius: 10px; border: 1px solid rgba(239,68,68,.12); }
.fail-rank .rank { font-weight: 800; color: #ef4444; }
.fail-rank .stat { font-size: 12px; color: #64748b; }
.chart-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 160px;
  padding: 20px;
  text-align: center;
  background: #f9fafb;
  border-radius: 12px;
  border: 1px dashed #e5e7eb;
}
.chart-empty-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #4b5563;
}
.chart-empty-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.5;
  max-width: 280px;
}
.ai-agent-section { margin-top: 4px; }
.ai-section-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.ai-section-hd h3 { margin: 0; font-size: 14px; font-weight: 800; }
.btn-analyze { font-size: 12px; font-weight: 700; color: #fff; background: linear-gradient(135deg, #d97706, #b45309); border: none; border-radius: 10px; padding: 8px 16px; cursor: pointer; }
.agpz-grid { display: grid; grid-template-columns: 240px 1fr 200px; gap: 12px; align-items: start; }
@media (max-width: 960px) { .charts-grid { grid-template-columns: 1fr; } .span2 { grid-column: auto; } .agpz-grid { grid-template-columns: 1fr; } }
.agpz-side, .agpz-main, .agpz-hist { padding: 14px 16px; }
.agpz-side-h { margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid #f1f5f9; }
.agpz-side-h h4 { margin: 0; font-size: 13px; font-weight: 800; }
.agpz-side-sub { margin: 4px 0 0; font-size: 10px; color: #94a3b8; }
.persona-card { text-align: center; margin-bottom: 12px; }
.persona-avatar { width: 48px; height: 48px; margin: 0 auto 8px; border-radius: 50%; background: linear-gradient(135deg, #fbbf24, #d97706); color: #fff; font-size: 20px; font-weight: 800; display: flex; align-items: center; justify-content: center; }
.persona-name { margin: 0; font-size: 13px; font-weight: 800; }
.persona-role { margin: 4px 0; font-size: 10px; color: #64748b; }
.persona-style { margin: 0; font-size: 10px; color: #94a3b8; }
.agpz-layer { margin-bottom: 10px; padding: 10px; border-radius: 10px; background: #fafafa; border: 1px solid #f1f5f9; }
.agpz-layer-head { display: flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 800; margin-bottom: 6px; }
.agpz-layer-tag { font-size: 10px; padding: 2px 6px; border-radius: 6px; background: rgba(217,119,6,.15); color: #b45309; }
.layer-text { margin: 0; font-size: 10px; line-height: 1.55; color: #475569; }
.agpz-editor-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.agpz-editor-head h4 { margin: 0; font-size: 13px; font-weight: 800; }
.llm-badge { font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 999px; background: rgba(16,185,129,.12); color: #059669; }
.analysis-loading { padding: 32px; text-align: center; color: #64748b; font-size: 13px; }
.analysis-placeholder { margin: 0; padding: 24px; text-align: center; color: #94a3b8; font-size: 12px; line-height: 1.6; }
.analysis-body { font-size: 13px; line-height: 1.65; color: #334155; max-height: 480px; overflow-y: auto; }
.md-body :deep(h1), .md-body :deep(h2), .md-body :deep(h3) { font-size: 14px; margin: 14px 0 8px; color: #0f172a; }
.md-body :deep(p), .md-body :deep(li) { margin: 0 0 8px; }
.md-body :deep(ul), .md-body :deep(ol) { padding-left: 20px; }
.digest-list { margin: 8px 0 0; padding-left: 18px; font-size: 11px; color: #64748b; line-height: 1.6; }
.agpz-hist h4 { margin: 0 0 8px; font-size: 12px; font-weight: 800; }
</style>
