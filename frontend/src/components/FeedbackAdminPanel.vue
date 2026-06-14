<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { authHeaders } from '../api/auth'
import FeedbackDashboard from './FeedbackDashboard.vue'
import ListPagination from './ListPagination.vue'
import ListQueryBar from './ListQueryBar.vue'
import type { FeedbackAdminItem } from '../types'
import { intentDisplay } from '../utils/intentLabels'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'

const rows = ref<FeedbackAdminItem[]>([])
const total = ref(0)
const loading = ref(false)
const detail = ref<FeedbackAdminItem | null>(null)
const detailLoading = ref(false)
const query = ref<ListQueryState>(defaultListQuery(20))
const extraRating = ref('')
const extraUserId = ref('')
const activeTab = ref<'dashboard' | 'list'>('dashboard')

const sortOptions = [
  { value: 'created_at', label: '提交时间' },
  { value: 'rating', label: '满意度' },
  { value: 'id', label: '反馈 ID' },
  { value: 'user_id', label: '用户 ID' },
]

const fmtDateTime = (s?: string): string => {
  if (!s) return '-'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const userLabel = (row: FeedbackAdminItem): string => row.nickname || row.username || `用户 #${row.user_id}`
const questionPreview = (row: FeedbackAdminItem): string => {
  const q = row.user_question || ''
  return q.length > 36 ? `${q.slice(0, 36)}…` : q || '（无提问记录）'
}
const starText = (n: number): string => `${'★'.repeat(n)}${'☆'.repeat(5 - n)}`
const intentLikedText = (liked?: boolean | null): string => {
  if (liked === true) return '👍 理解准确'
  if (liked === false) return '👎 理解有误'
  return '未评价'
}

const loadList = async (): Promise<void> => {
  loading.value = true
  try {
    const qs = toSearchParams(query.value, {
      rating: extraRating.value || undefined,
      user_id: extraUserId.value || undefined,
    })
    const res = await fetch(`/api/v1/admin/feedback?${qs}`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      rows.value = data.items || []
      total.value = data.total || 0
      if (data.page) query.value.page = data.page
      if (data.size) query.value.size = data.size
    }
  } finally {
    loading.value = false
  }
}

const resetQuery = (): void => {
  query.value = defaultListQuery(20)
  extraRating.value = ''
  extraUserId.value = ''
  loadList()
}

const openDetail = async (row: FeedbackAdminItem): Promise<void> => {
  detailLoading.value = true
  detail.value = row
  try {
    const res = await fetch(`/api/v1/admin/feedback/${row.id}`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      detail.value = data.item || row
    }
  } finally {
    detailLoading.value = false
  }
}

const closeDetail = (): void => {
  detail.value = null
}

watch(() => [query.value.page, query.value.size], loadList)

onMounted(loadList)
</script>

<template>
  <div class="feedback-admin">
    <nav class="haici-subnav" aria-label="用户反馈子菜单">
      <button
        type="button"
        class="haici-subnav-item"
        :class="{ 'haici-subnav-item--active': activeTab === 'dashboard' }"
        @click="activeTab = 'dashboard'"
      >
        <i class="fas fa-chart-pie haici-subnav-icon" aria-hidden="true" />
        <span class="haici-subnav-label">综合看板</span>
      </button>
      <button
        type="button"
        class="haici-subnav-item"
        :class="{ 'haici-subnav-item--active': activeTab === 'list' }"
        @click="activeTab = 'list'"
      >
        <i class="fas fa-list haici-subnav-icon" aria-hidden="true" />
        <span class="haici-subnav-label">反馈列表</span>
      </button>
    </nav>

    <FeedbackDashboard v-if="activeTab === 'dashboard'" />

    <div v-show="activeTab === 'list'" class="feedback-admin-list card">
      <div class="feedback-list-toolbar">
        <p class="feedback-list-toolbar-meta">共 <strong>{{ total }}</strong> 条反馈</p>
        <button type="button" class="haici-btn haici-btn--accent" :disabled="loading" @click="loadList">
          {{ loading ? '加载中…' : '刷新列表' }}
        </button>
      </div>

      <div class="feedback-list-filters">
        <ListQueryBar
          v-model="query"
          :sort-options="sortOptions"
          name-placeholder="用户名/昵称"
          keyword-placeholder="补充说明关键词"
          @search="loadList"
          @reset="resetQuery"
        />
        <div class="extra-filters">
          <label>用户 ID <input v-model="extraUserId" type="text" placeholder="精确" @keyup.enter="loadList" /></label>
          <label>星级
            <select v-model="extraRating" @change="query.page = 1; loadList()">
              <option value="">全部</option>
              <option v-for="n in 5" :key="n" :value="String(n)">{{ n }} 星</option>
            </select>
          </label>
        </div>
      </div>

      <div class="table-wrap">
        <table class="feedback-table">
          <thead>
            <tr>
              <th>ID</th><th>用户</th><th>提交时间</th><th>满意度</th><th>意图评价</th><th>提问摘要</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>#{{ row.id }}</td>
              <td>{{ userLabel(row) }}</td>
              <td class="nowrap">{{ fmtDateTime(row.created_at) }}</td>
              <td class="stars">{{ starText(row.rating) }}</td>
              <td>{{ intentLikedText(row.intent_liked) }}</td>
              <td class="preview">{{ questionPreview(row) }}</td>
              <td><button type="button" class="haici-btn haici-btn--accent" @click="openDetail(row)">查看详情</button></td>
            </tr>
          </tbody>
        </table>
        <p v-if="!rows.length && !loading" class="empty">暂无用户反馈</p>
      </div>
      <ListPagination v-model:page="query.page" v-model:size="query.size" :total="total" />
    </div>

    <div v-if="detail" class="feedback-detail-mask" @click.self="closeDetail">
      <div class="feedback-detail-panel card">
        <div class="detail-hd">
          <h3>反馈详情 #{{ detail.id }}</h3>
          <button type="button" class="btn-close" @click="closeDetail">✕</button>
        </div>
        <p v-if="detailLoading" class="detail-loading">正在加载完整详情…</p>
        <div v-else class="detail-body">
          <section class="detail-section"><h4>一、反馈元信息</h4>
            <dl class="detail-dl">
              <div><dt>提交用户</dt><dd>{{ userLabel(detail) }}（ID {{ detail.user_id }}）</dd></div>
              <div><dt>提交时间</dt><dd>{{ fmtDateTime(detail.created_at) }}</dd></div>
              <div><dt>回答满意度</dt><dd><span class="stars">{{ starText(detail.rating) }}</span>（{{ detail.rating }} 星）</dd></div>
              <div><dt>意图理解评价</dt><dd>{{ intentLikedText(detail.intent_liked) }}</dd></div>
            </dl>
          </section>
          <section class="detail-section"><h4>二、用户评价补充</h4><pre class="detail-block">{{ detail.comment?.trim() || '（用户未填写补充说明）' }}</pre></section>
          <section class="detail-section"><h4>三、会话标识</h4>
            <dl class="detail-dl">
              <div><dt>追踪 ID</dt><dd class="mono">{{ detail.context_id || '—' }}</dd></div>
              <div><dt>会话 ID</dt><dd>{{ detail.session_id ?? '—' }}</dd></div>
              <div><dt>消息 ID</dt><dd>{{ detail.message_id }}</dd></div>
              <div v-if="detail.session_title"><dt>会话标题</dt><dd>{{ detail.session_title }}</dd></div>
            </dl>
          </section>
          <section class="detail-section"><h4>四、意图识别</h4>
            <p class="detail-intent">{{ intentDisplay(detail.intent, detail.intent_label) }}</p>
            <p v-if="detail.corrected_intent_label" class="detail-corrected">
              用户纠偏意图：{{ detail.corrected_intent_label }}
              <span v-if="detail.corrected_intent" class="mono">（{{ detail.corrected_intent }}）</span>
            </p>
          </section>
          <section class="detail-section"><h4>五、本轮用户提问</h4><pre class="detail-block highlight-user">{{ detail.user_question || '（无记录）' }}</pre></section>
          <section class="detail-section"><h4>六、本轮 AI 回答</h4><pre class="detail-block highlight-ai">{{ detail.assistant_answer || '（无记录）' }}</pre></section>
          <section class="detail-section"><h4>七、上下文全文摘要</h4><pre class="detail-block highlight-summary">{{ detail.context_summary || '（无摘要）' }}</pre></section>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.feedback-admin {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: stretch;
  min-height: 0;
}
.card { background: #fff; border: 1px solid rgba(54,62,66,.1); border-radius: 16px; overflow: hidden; }
.feedback-list-filters { padding: 0 12px 4px; }
.feedback-list-filters :deep(.list-query-bar) {
  margin-bottom: 8px;
  border: none;
  background: transparent;
  padding: 12px 4px 0;
}
.extra-filters { display: flex; flex-wrap: wrap; gap: 12px; padding: 0 4px 8px; font-size: 12px; color: #374151; }
.extra-filters label { display: flex; align-items: center; gap: 6px; font-weight: 600; }
.extra-filters input, .extra-filters select {
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
  color: #111827;
  background: #fff;
}
.table-wrap { overflow-x: auto; }
.feedback-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.feedback-table th { text-align: left; padding: 10px 12px; background: #f9fafb; color: #374151; font-weight: 700; border-bottom: 1px solid #e5e7eb; }
.feedback-table td { padding: 10px 12px; border-top: 1px solid #f3f4f6; color: #1f2937; }
.feedback-table tbody tr:hover { background: #fafafa; }
.nowrap { white-space: nowrap; }
.stars { color: #f59e0b; font-weight: 700; }
.preview { max-width: 220px; color: #475569; }
.empty { padding: 32px; text-align: center; color: #94a3b8; }
.feedback-detail-mask { position: fixed; inset: 0; z-index: 80; background: rgba(15,23,42,.45); display: flex; align-items: center; justify-content: center; padding: 24px; }
.feedback-detail-panel { width: min(720px,100%); max-height: 90vh; display: flex; flex-direction: column; box-shadow: 0 20px 50px rgba(15,23,42,.2); }
.detail-hd { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid rgba(54,62,66,.08); }
.detail-hd h3 { margin: 0; font-size: 15px; font-weight: 800; }
.btn-close { width: 32px; height: 32px; border: none; border-radius: 8px; background: #f1f5f9; cursor: pointer; }
.detail-loading { padding: 24px; text-align: center; color: #64748b; }
.detail-body { overflow-y: auto; padding: 12px 16px 20px; }
.detail-section { margin-bottom: 16px; }
.detail-section h4 { margin: 0 0 8px; font-size: 12px; font-weight: 800; color: #d97706; }
.detail-dl { margin: 0; display: grid; gap: 6px; }
.detail-dl > div { display: grid; grid-template-columns: 110px 1fr; gap: 8px; font-size: 12px; }
.detail-dl dt { color: #64748b; font-weight: 700; }
.detail-dl dd { margin: 0; word-break: break-word; }
.mono { font-family: ui-monospace, monospace; font-size: 11px; }
.detail-intent { margin: 0; font-size: 13px; font-weight: 700; }
.detail-corrected { margin: 8px 0 0; font-size: 12px; color: #15803d; font-weight: 600; }
.detail-block { margin: 0; padding: 12px; border-radius: 10px; border: 1px solid rgba(54,62,66,.1); background: #f8fafc; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 220px; overflow: auto; font-family: inherit; }
.highlight-user { background: rgba(217,119,6,.08); }
.highlight-summary { max-height: 280px; }
</style>
