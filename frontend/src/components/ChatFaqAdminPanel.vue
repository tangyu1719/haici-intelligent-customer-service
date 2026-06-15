<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'
import type { ChatFaqItem } from '../types'

const rows = ref<ChatFaqItem[]>([])
const loading = ref(false)
const saving = ref(false)
const msg = ref('')
const editingId = ref<number | null>(null)
const form = ref({
  category: '通用',
  question: '',
  answer: '',
  sort_order: 0,
  enabled: true,
})

const fmtDateTime = (s?: string | null): string => {
  if (!s) return '-'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN')
}

const resetForm = (): void => {
  editingId.value = null
  form.value = { category: '通用', question: '', answer: '', sort_order: rows.value.length + 1, enabled: true }
}

const loadRows = async (): Promise<void> => {
  loading.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/v1/admin/chat-faq', { headers: authHeaders() })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '加载失败')
    rows.value = data.items || []
  } catch (e) {
    msg.value = (e as Error).message || '加载 FAQ 失败'
  } finally {
    loading.value = false
  }
}

const startEdit = (row: ChatFaqItem): void => {
  editingId.value = row.id
  form.value = {
    category: row.category || '通用',
    question: row.question,
    answer: row.answer,
    sort_order: row.sort_order ?? 0,
    enabled: row.enabled !== 0,
  }
}

const saveForm = async (): Promise<void> => {
  if (!form.value.question.trim() || !form.value.answer.trim()) {
    msg.value = '请填写问题和缓存答案'
    return
  }
  saving.value = true
  msg.value = ''
  try {
    const body = {
      category: form.value.category.trim() || '通用',
      question: form.value.question.trim(),
      answer: form.value.answer.trim(),
      sort_order: form.value.sort_order,
      enabled: form.value.enabled,
    }
    const url = editingId.value
      ? `/api/v1/admin/chat-faq/${editingId.value}`
      : '/api/v1/admin/chat-faq'
    const res = await fetch(url, {
      method: editingId.value ? 'PUT' : 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '保存失败')
    msg.value = editingId.value ? '已更新 FAQ' : '已新增 FAQ'
    resetForm()
    await loadRows()
  } catch (e) {
    msg.value = (e as Error).message || '保存失败'
  } finally {
    saving.value = false
  }
}

const removeRow = async (id: number): Promise<void> => {
  if (!window.confirm('确定删除该 FAQ？删除后对话页将不再展示。')) return
  saving.value = true
  msg.value = ''
  try {
    const res = await fetch(`/api/v1/admin/chat-faq/${id}`, { method: 'DELETE', headers: authHeaders() })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || '删除失败')
    if (editingId.value === id) resetForm()
    msg.value = '已删除'
    await loadRows()
  } catch (e) {
    msg.value = (e as Error).message || '删除失败'
  } finally {
    saving.value = false
  }
}

const enabledCount = computed(() => rows.value.filter((r) => r.enabled !== 0).length)

onMounted(() => {
  resetForm()
  void loadRows()
})
</script>

<template>
  <div class="faq-admin">
    <div class="faq-admin-hd">
      <div>
        <h2 class="faq-admin-title">对话 FAQ 配置</h2>
        <p class="faq-admin-desc">
          维护对话页欢迎区的标准问答缓存。用户点击后将<strong>直接展示此处配置的标准答案</strong>，不调用 RAG/LLM。
          建议每日根据运营需要更新。
        </p>
      </div>
      <div class="faq-admin-meta">已启用 {{ enabledCount }} / {{ rows.length }} 条</div>
    </div>

    <div class="faq-admin-form">
      <div class="faq-admin-form-title">{{ editingId ? `编辑 FAQ #${editingId}` : '新增 FAQ' }}</div>
      <div class="faq-admin-form-grid">
        <label class="faq-field">
          <span>分类</span>
          <input v-model="form.category" class="faq-input" maxlength="64" placeholder="如：运维助手 / 售后政策" />
        </label>
        <label class="faq-field">
          <span>排序</span>
          <input v-model.number="form.sort_order" type="number" min="0" max="9999" class="faq-input" />
        </label>
        <label class="faq-field faq-field--full">
          <span>问题</span>
          <input v-model="form.question" class="faq-input" maxlength="500" placeholder="用户看到并点击的问题" />
        </label>
        <label class="faq-field faq-field--full">
          <span>缓存答案</span>
          <textarea v-model="form.answer" class="faq-textarea" rows="6" maxlength="8000" placeholder="点击后直接展示的标准答案（可含换行）" />
        </label>
        <label class="faq-check">
          <input v-model="form.enabled" type="checkbox" />
          <span>启用（对话页展示）</span>
        </label>
      </div>
      <div class="faq-admin-form-actions">
        <button type="button" class="haici-btn haici-btn--primary" :disabled="saving" @click="saveForm">
          {{ saving ? '保存中…' : (editingId ? '保存修改' : '新增 FAQ') }}
        </button>
        <button v-if="editingId" type="button" class="haici-btn" :disabled="saving" @click="resetForm">取消编辑</button>
      </div>
    </div>

    <p v-if="msg" class="faq-admin-msg">{{ msg }}</p>

    <div class="faq-admin-table-wrap">
      <table class="faq-admin-table">
        <thead>
          <tr>
            <th>排序</th>
            <th>分类</th>
            <th>问题</th>
            <th>缓存答案预览</th>
            <th>状态</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="7" class="faq-empty">加载中…</td>
          </tr>
          <tr v-else-if="!rows.length">
            <td colspan="7" class="faq-empty">暂无 FAQ，请在上方新增</td>
          </tr>
          <tr v-for="row in rows" :key="row.id">
            <td>{{ row.sort_order ?? 0 }}</td>
            <td>{{ row.category }}</td>
            <td class="faq-q-cell">{{ row.question }}</td>
            <td class="faq-a-cell">{{ row.answer }}</td>
            <td>
              <span :class="row.enabled === 0 ? 'faq-badge faq-badge--off' : 'faq-badge faq-badge--on'">
                {{ row.enabled === 0 ? '停用' : '启用' }}
              </span>
            </td>
            <td class="faq-time">{{ fmtDateTime(row.updated_at) }}</td>
            <td class="faq-actions">
              <button type="button" class="faq-link" @click="startEdit(row)">编辑</button>
              <button type="button" class="faq-link faq-link--danger" @click="removeRow(row.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.faq-admin {
  max-width: 1100px;
  margin: 0 auto;
}
.faq-admin-hd {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.faq-admin-title {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 800;
  color: #363e42;
}
.faq-admin-desc {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}
.faq-admin-meta {
  font-size: 12px;
  font-weight: 700;
  color: #d97706;
  white-space: nowrap;
}
.faq-admin-form {
  background: #fff;
  border: 1px solid rgba(54, 62, 66, 0.12);
  border-radius: 14px;
  padding: 16px;
  margin-bottom: 12px;
}
.faq-admin-form-title {
  font-size: 13px;
  font-weight: 800;
  color: #363e42;
  margin-bottom: 12px;
}
.faq-admin-form-grid {
  display: grid;
  grid-template-columns: 1fr 120px;
  gap: 10px 12px;
}
.faq-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}
.faq-field--full {
  grid-column: 1 / -1;
}
.faq-input,
.faq-textarea {
  border: 1px solid rgba(54, 62, 66, 0.15);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  color: #363e42;
}
.faq-textarea {
  resize: vertical;
  min-height: 120px;
  line-height: 1.55;
}
.faq-check {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #475569;
}
.faq-admin-form-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.faq-admin-msg {
  margin: 0 0 12px;
  font-size: 12px;
  font-weight: 700;
  color: #d97706;
}
.faq-admin-table-wrap {
  background: #fff;
  border: 1px solid rgba(54, 62, 66, 0.12);
  border-radius: 14px;
  overflow: auto;
}
.faq-admin-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.faq-admin-table th,
.faq-admin-table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(54, 62, 66, 0.08);
  text-align: left;
  vertical-align: top;
}
.faq-admin-table th {
  background: #fafafa;
  color: #64748b;
  font-weight: 700;
}
.faq-q-cell {
  font-weight: 700;
  color: #363e42;
  min-width: 180px;
}
.faq-a-cell {
  color: #64748b;
  max-width: 360px;
  white-space: pre-wrap;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.faq-time {
  white-space: nowrap;
  color: #94a3b8;
}
.faq-empty {
  text-align: center;
  color: #94a3b8;
  padding: 24px;
}
.faq-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}
.faq-badge--on {
  background: rgba(34, 197, 94, 0.12);
  color: #15803d;
}
.faq-badge--off {
  background: rgba(148, 163, 184, 0.18);
  color: #64748b;
}
.faq-actions {
  white-space: nowrap;
}
.faq-link {
  border: none;
  background: none;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  margin-right: 8px;
}
.faq-link--danger {
  color: #dc2626;
}
</style>
