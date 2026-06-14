<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'
import ListPagination from './ListPagination.vue'
import type { FeedbackAdminItem } from '../types'
import { intentDisplay } from '../utils/intentLabels'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'

const rows = ref<FeedbackAdminItem[]>([])
const total = ref(0)
const loading = ref(false)
const query = ref<ListQueryState>(defaultListQuery(15))

const fmtTime = (s?: string): string => {
  if (!s) return '-'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN', { hour12: false })
}

const commentHistory = (row: FeedbackAdminItem): Array<{ text: string; created_at?: string }> => {
  const snap = row.context_snapshot as { comments_history?: Array<{ text: string; created_at?: string }> } | null
  const hist = snap?.comments_history
  if (Array.isArray(hist) && hist.length) return hist
  if (row.comment) return [{ text: row.comment, created_at: row.created_at }]
  return []
}

const loadRows = async (): Promise<void> => {
  loading.value = true
  try {
    const qs = toSearchParams({ ...query.value, sortBy: 'created_at', sortOrder: 'desc' })
    const res = await fetch(`/api/v1/feedback/my?${qs}`, { headers: authHeaders() })
    if (!res.ok) return
    const data = await res.json()
    rows.value = data.items || []
    total.value = data.total || 0
    if (data.page) query.value.page = data.page
    if (data.size) query.value.size = data.size
  } finally {
    loading.value = false
  }
}

onMounted(loadRows)
</script>

<template>
  <div class="profile-feedback-page">
    <header class="pf-hd">
      <h2 class="pf-title">回答反馈记录</h2>
      <p class="pf-desc">您对 AI 回答的星级评价与补充说明均会保存在此处。</p>
    </header>

    <div v-if="loading" class="pf-empty">加载中…</div>
    <div v-else-if="!rows.length" class="pf-empty">暂无反馈记录</div>
    <div v-else class="pf-list">
      <article v-for="row in rows" :key="row.id" class="pf-card">
        <div class="pf-card-hd">
          <span class="pf-stars">{{ '★'.repeat(row.rating) }}{{ '☆'.repeat(5 - row.rating) }}</span>
          <span class="pf-time">{{ fmtTime(row.created_at) }}</span>
        </div>
        <div class="pf-meta">
          <span v-if="row.intent_label || row.intent">意图：{{ intentDisplay(row.intent, row.intent_label) }}</span>
          <span v-if="row.intent_liked === true" class="pf-intent-ok">👍 理解准确</span>
          <span v-else-if="row.intent_liked === false" class="pf-intent-bad">👎 理解有误</span>
          <span v-if="row.session_id">会话 #{{ row.session_id }}</span>
        </div>
        <div v-if="row.user_question" class="pf-block">
          <div class="pf-label">我的提问</div>
          <p class="pf-text">{{ row.user_question }}</p>
        </div>
        <div v-if="row.assistant_answer" class="pf-block">
          <div class="pf-label">AI 回答摘要</div>
          <p class="pf-text pf-text-muted">{{ row.assistant_answer.slice(0, 280) }}{{ row.assistant_answer.length > 280 ? '…' : '' }}</p>
        </div>
        <div v-if="commentHistory(row).length" class="pf-block">
          <div class="pf-label">补充说明</div>
          <ul class="pf-comments">
            <li v-for="(c, i) in commentHistory(row)" :key="i">
              <span class="pf-comment-time">{{ fmtTime(c.created_at) }}</span>
              <p class="pf-text">{{ c.text }}</p>
            </li>
          </ul>
        </div>
      </article>
    </div>

    <ListPagination
      v-model:page="query.page"
      v-model:size="query.size"
      :total="total"
      class="pf-pager"
      @update:page="loadRows"
      @update:size="loadRows"
    />
  </div>
</template>

<style scoped>
.profile-feedback-page {
  max-width: 720px;
  margin: 0 auto;
}
.pf-hd {
  margin-bottom: 16px;
}
.pf-title {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: #363e42;
}
.pf-desc {
  margin: 6px 0 0;
  font-size: 12px;
  color: #64748b;
}
.pf-empty {
  text-align: center;
  padding: 48px 16px;
  color: #94a3b8;
  font-size: 13px;
}
.pf-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.pf-card {
  background: #fff;
  border: 1px solid rgba(54, 62, 66, 0.1);
  border-radius: 16px;
  padding: 14px 16px;
}
.pf-card-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.pf-stars {
  color: #f59e0b;
  font-size: 14px;
}
.pf-time {
  font-size: 11px;
  color: #94a3b8;
}
.pf-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  font-size: 11px;
  color: #64748b;
  margin-bottom: 10px;
}
.pf-intent-ok {
  color: #15803d;
}
.pf-intent-bad {
  color: #b91c1c;
}
.pf-block {
  margin-top: 8px;
}
.pf-label {
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
  margin-bottom: 4px;
}
.pf-text {
  font-size: 13px;
  line-height: 1.5;
  color: #363e42;
  margin: 0;
  white-space: pre-wrap;
}
.pf-text-muted {
  color: #4b5563;
}
.pf-comments {
  list-style: none;
  margin: 0;
  padding: 0;
}
.pf-comments li {
  padding: 8px 10px;
  border-radius: 10px;
  background: #faf9f7;
  border: 1px solid rgba(54, 62, 66, 0.08);
  margin-bottom: 6px;
}
.pf-comment-time {
  font-size: 10px;
  color: #94a3b8;
}
.pf-pager {
  margin-top: 16px;
}
</style>
