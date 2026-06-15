<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { authHeaders, hasPerm } from '../api/auth'
import type { ChatMessageItem, ChatSessionDetail, ChatSessionItem } from '../types'
import ListPagination from './ListPagination.vue'
import ListQueryBar from './ListQueryBar.vue'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'
import { intentDisplay } from '../utils/intentLabels'
import {
  exportSessionJson,
  exportSessionListCsv,
  exportSessionMarkdown,
} from '../utils/sessionExport'

const sessionList = ref<ChatSessionItem[]>([])
const sessionTotal = ref(0)
const sessionQuery = ref<ListQueryState>(defaultListQuery(20))
const msgKeyword = ref('')
const sessionMessages = ref<ChatMessageItem[]>([])
const msgLoading = ref(false)
const selectedSessionId = ref<number | null>(null)
const sessionDetail = ref<ChatSessionDetail | null>(null)
const editingSessionId = ref<number | null>(null)
const editingSessionTitle = ref('')
const editingSessionNote = ref('')
const listExporting = ref(false)
const sessionExporting = ref(false)
const canViewAll = computed(() => hasPerm('session:view:all'))
const filterUserId = ref('')
const filterUserKeyword = ref('')
const userOptions = ref<Array<{ id: number; label: string }>>([])
const persistIntervalHint = ref(10)

const userDisplayLabel = (s: ChatSessionItem): string => {
  if (s.nickname) return s.nickname
  if (s.username) return s.username
  if (s.user_no) return `#${s.user_no}`
  return s.user_id ? `用户 ${s.user_id}` : '-'
}

const loadPersistInterval = async (): Promise<void> => {
  const res = await fetch('/api/v1/sessions/settings/persist-interval', { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    persistIntervalHint.value = data.session_active_persist_interval_minutes ?? 10
  }
}

const searchUsers = async (): Promise<void> => {
  if (!canViewAll.value) return
  const kw = filterUserKeyword.value.trim()
  const qs = toSearchParams({ ...defaultListQuery(20), keyword: kw, page: 1, size: 20 })
  const res = await fetch(`/api/v1/admin/rbac/users?${qs}`, { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    userOptions.value = (data.items || []).map((u: { id: number; nickname?: string; username?: string; user_no?: string }) => ({
      id: u.id,
      label: u.nickname || u.username || `#${u.user_no || u.id}`,
    }))
  }
}

const fmtDateTime = (s?: string): string => {
  if (!s) return '-'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

const statusLabel = (status?: number): string => (status === 0 ? '已归档' : '正常')

const previewMessages = computed(() => {
  const msgs = sessionMessages.value
  if (msgs.length <= 2) return msgs
  return [msgs[0], msgs[msgs.length - 1]]
})

const filteredMessages = computed(() => {
  const kw = msgKeyword.value.trim().toLowerCase()
  if (!kw) return sessionMessages.value
  return sessionMessages.value.filter((m) => m.content.toLowerCase().includes(kw))
})

const loadSessions = async (): Promise<void> => {
  if (!hasPerm('session:view')) return
  const extra: Record<string, string | undefined> = {}
  if (canViewAll.value && filterUserId.value.trim()) {
    extra.user_id = filterUserId.value.trim()
  }
  const qs = toSearchParams(sessionQuery.value, extra)
  const res = await fetch(`/api/v1/sessions?${qs}`, { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    sessionList.value = data.items || []
    sessionTotal.value = data.total || 0
    if (data.page) sessionQuery.value.page = data.page
    if (data.size) sessionQuery.value.size = data.size
  }
}

const resetSessionQuery = (): void => {
  sessionQuery.value = defaultListQuery(20)
  filterUserId.value = ''
  filterUserKeyword.value = ''
  userOptions.value = []
  loadSessions()
}

const loadAllSessionMessages = async (sessionId: number, totalHint?: number): Promise<void> => {
  msgLoading.value = true
  try {
    const all: ChatMessageItem[] = []
    let page = 1
    const size = 100
    let total = totalHint || 0
    while (true) {
      const qs = toSearchParams({
        ...defaultListQuery(size),
        page,
        size,
        sortBy: 'created_at',
        sortOrder: 'asc',
      })
      const res = await fetch(`/api/v1/sessions/${sessionId}/messages?${qs}`, { headers: authHeaders() })
      if (!res.ok) break
      const data = await res.json()
      const batch: ChatMessageItem[] = data.items || []
      all.push(...batch)
      total = data.total ?? total
      if (!batch.length || all.length >= total) break
      page += 1
    }
    sessionMessages.value = all
  } finally {
    msgLoading.value = false
  }
}

const openSessionDetail = async (id: number): Promise<void> => {
  selectedSessionId.value = id
  editingSessionId.value = null
  msgKeyword.value = ''
  sessionMessages.value = []
  const res = await fetch(`/api/v1/sessions/${id}`, { headers: authHeaders() })
  if (res.ok) {
    sessionDetail.value = await res.json()
    await loadAllSessionMessages(id, sessionDetail.value?.message_count)
  }
}

const closeSessionDetail = (): void => {
  selectedSessionId.value = null
  sessionDetail.value = null
  sessionMessages.value = []
  msgKeyword.value = ''
}

const startEditSessionRow = (s: ChatSessionItem, e?: Event): void => {
  e?.stopPropagation()
  editingSessionId.value = s.id
  editingSessionTitle.value = s.title || ''
  editingSessionNote.value = s.meta?.note || ''
}

const cancelEditSessionRow = (): void => {
  editingSessionId.value = null
  editingSessionTitle.value = ''
  editingSessionNote.value = ''
}

const saveEditSessionRow = async (id: number): Promise<void> => {
  const title = editingSessionTitle.value.trim()
  if (!title) return
  const res = await fetch(`/api/v1/sessions/${id}`, {
    method: 'PATCH',
    headers: authHeaders(),
    body: JSON.stringify({ title, note: editingSessionNote.value.trim() || '' }),
  })
  if (!res.ok) return
  cancelEditSessionRow()
  await loadSessions()
  if (selectedSessionId.value === id) await openSessionDetail(id)
}

const archiveSessionRow = async (id: number, e?: Event): Promise<void> => {
  e?.stopPropagation()
  if (!window.confirm('确定删除该会话？删除后将从您的列表中隐藏，管理员仍可在「会话审计」中查看完整记录。')) return
  const res = await fetch(`/api/v1/sessions/${id}`, { method: 'DELETE', headers: authHeaders() })
  if (!res.ok) {
    window.alert('删除失败，请稍后重试')
    return
  }
  if (selectedSessionId.value === id) closeSessionDetail()
  await loadSessions()
}

const roleLabel = (role: string): string => {
  if (role === 'user') return '用户'
  if (role === 'assistant') return '助手'
  if (role === 'system') return '系统'
  return role
}

const fetchAllSessionsForExport = async (): Promise<ChatSessionItem[]> => {
  const all: ChatSessionItem[] = []
  let page = 1
  const size = 100
  let total = 0
  while (true) {
    const qs = toSearchParams({ ...sessionQuery.value, page, size })
    const res = await fetch(`/api/v1/sessions?${qs}`, { headers: authHeaders() })
    if (!res.ok) break
    const data = await res.json()
    const batch: ChatSessionItem[] = data.items || []
    all.push(...batch)
    total = data.total ?? total
    if (!batch.length || all.length >= total) break
    page += 1
  }
  return all
}

const exportSessionList = async (): Promise<void> => {
  if (listExporting.value) return
  listExporting.value = true
  try {
    const items = await fetchAllSessionsForExport()
    if (!items.length) {
      window.alert('当前筛选条件下没有可导出的会话')
      return
    }
    exportSessionListCsv(items)
  } finally {
    listExporting.value = false
  }
}

const exportCurrentSession = async (format: 'json' | 'md'): Promise<void> => {
  if (sessionExporting.value || !sessionDetail.value) return
  sessionExporting.value = true
  try {
    let messages = sessionMessages.value
    if (!messages.length && selectedSessionId.value) {
      await loadAllSessionMessages(selectedSessionId.value, sessionDetail.value.message_count)
      messages = sessionMessages.value
    }
    if (format === 'json') {
      exportSessionJson(sessionDetail.value, messages)
    } else {
      exportSessionMarkdown(sessionDetail.value, messages)
    }
  } finally {
    sessionExporting.value = false
  }
}

watch(() => [sessionQuery.value.page, sessionQuery.value.size], loadSessions)

onMounted(async () => {
  await loadPersistInterval()
  await loadSessions()
})
</script>

<template>
  <div class="session-history flex flex-col min-h-0 h-full">
    <div
      class="flex-1 min-h-0 grid gap-4"
      :class="selectedSessionId ? 'grid-cols-1 xl:grid-cols-12' : 'grid-cols-1'"
    >
      <!-- 会话列表 -->
      <div
        class="bg-white rounded-2xl border overflow-hidden flex flex-col min-h-0"
        :class="selectedSessionId ? 'xl:col-span-3' : 'max-w-6xl mx-auto w-full'"
      >
        <ListQueryBar
          v-model="sessionQuery"
          :sort-options="[
            { value: 'updated_at', label: '最后更新' },
            { value: 'created_at', label: '创建时间' },
            { value: 'title', label: '会话名称' },
            { value: 'id', label: '会话 ID' },
          ]"
          name-placeholder="会话标题"
          keyword-placeholder="标题/追踪 ID"
          @search="loadSessions"
          @reset="resetSessionQuery"
        />
        <div class="session-list-toolbar">
          <button
            type="button"
            class="export-btn"
            :disabled="listExporting"
            @click="exportSessionList"
          >
            {{ listExporting ? '导出中…' : '导出列表 CSV' }}
          </button>
          <span class="export-hint">按当前筛选条件导出全部会话</span>
        </div>
        <div class="flex-1 min-h-0 overflow-y-auto">
          <table class="w-full text-sm">
            <thead class="bg-[#fcfcfc] text-[#363e42]/60 text-[11px] sticky top-0 z-10">
              <tr>
                <th class="p-3 text-left">ID</th>
                <th v-if="!selectedSessionId" class="p-3 text-left">追踪 ID</th>
                <th class="p-3 text-left">名称</th>
                <th v-if="!selectedSessionId" class="p-3 text-left">创建时间</th>
                <th class="p-3 text-left">最后更新</th>
                <th class="p-3 text-left">消息</th>
                <th class="p-3 text-left">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="s in sessionList"
                :key="s.id"
                class="border-t cursor-pointer hover:bg-[#fdf6e3]/30"
                :class="selectedSessionId === s.id ? 'bg-[#d97706]/10' : ''"
                @click="openSessionDetail(s.id)"
              >
                <td class="p-3 font-mono text-[11px]">{{ s.id }}</td>
                <td v-if="!selectedSessionId" class="p-3 font-mono text-[10px] text-[#363e42]/60 max-w-[120px] truncate" :title="s.context_id">{{ s.context_id }}</td>
                <td class="p-3">
                  <template v-if="editingSessionId === s.id">
                    <input v-model="editingSessionTitle" class="w-full border rounded px-2 py-1 text-[12px] mb-1" maxlength="200" @click.stop />
                    <input v-model="editingSessionNote" class="w-full border rounded px-2 py-1 text-[11px]" placeholder="备注（可选）" maxlength="500" @click.stop />
                  </template>
                  <template v-else>
                    <div class="font-bold">{{ s.title || `会话 #${s.id}` }}</div>
                    <div v-if="s.meta?.note" class="text-[10px] text-[#363e42]/50 mt-0.5">{{ s.meta.note }}</div>
                  </template>
                </td>
                <td v-if="!selectedSessionId" class="p-3 text-[11px] whitespace-nowrap">{{ fmtDateTime(s.created_at) }}</td>
                <td class="p-3 text-[11px] whitespace-nowrap">{{ fmtDateTime(s.updated_at) }}</td>
                <td class="p-3 text-[11px]">{{ s.message_count ?? s.meta?.message_count ?? 0 }}</td>
                <td class="p-3 whitespace-nowrap" @click.stop>
                  <template v-if="editingSessionId === s.id">
                    <button class="text-[11px] text-[#d97706] font-bold mr-2" @click="saveEditSessionRow(s.id)">保存</button>
                    <button class="text-[11px] text-[#363e42]/50" @click="cancelEditSessionRow">取消</button>
                  </template>
                  <template v-else>
                    <button class="text-[11px] text-[#363e42] font-bold mr-2" @click="startEditSessionRow(s, $event)">编辑</button>
                    <button class="text-[11px] text-red-500" title="从界面删除（管理员仍可审计）" @click="archiveSessionRow(s.id, $event)">🗑 删除</button>
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="!sessionList.length" class="p-8 text-center text-[#363e42]/40 text-sm">暂无历史会话</p>
        </div>
        <ListPagination v-model:page="sessionQuery.page" v-model:size="sessionQuery.size" :total="sessionTotal" />
      </div>

      <!-- 主区域：完整对话上下文 -->
      <div
        v-if="selectedSessionId && sessionDetail"
        class="xl:col-span-6 bg-white rounded-2xl border flex flex-col min-h-0 min-h-[480px]"
      >
        <div class="p-4 border-b shrink-0 flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h3 class="font-black text-base truncate">{{ sessionDetail.title }}</h3>
            <p class="text-[11px] text-[#363e42]/50 mt-1">
              会话 #{{ sessionDetail.id }} · 共 {{ sessionMessages.length }} 条消息
            </p>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <button
              type="button"
              class="export-btn text-red-600 border-red-200"
              title="从界面删除（管理员仍可审计）"
              @click="archiveSessionRow(sessionDetail.id, $event)"
            >
              删除会话
            </button>
            <button
              type="button"
              class="export-btn"
              :disabled="sessionExporting || msgLoading"
              @click="exportCurrentSession('json')"
            >
              导出 JSON
            </button>
            <button
              type="button"
              class="export-btn"
              :disabled="sessionExporting || msgLoading"
              @click="exportCurrentSession('md')"
            >
              导出 Markdown
            </button>
            <button type="button" class="close-detail-btn" @click="closeSessionDetail">
              关闭详情
            </button>
          </div>
        </div>

        <div class="px-4 py-2 border-b shrink-0 flex items-center gap-2">
          <input
            v-model="msgKeyword"
            type="text"
            class="flex-1 border rounded-lg px-3 py-1.5 text-[12px]"
            placeholder="在对话中搜索关键词…"
          />
          <button v-if="msgKeyword" type="button" class="text-[11px] text-[#363e42]/50 px-2" @click="msgKeyword = ''">清除</button>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
          <p v-if="msgLoading" class="text-center text-[#363e42]/40 text-sm py-8">正在加载完整对话…</p>
          <template v-else>
            <div
              v-for="m in filteredMessages"
              :key="m.id"
              class="p-4 rounded-xl text-[13px] border leading-relaxed"
              :class="m.role === 'user' ? 'bg-[#d97706]/10 border-[#d97706]/20' : m.role === 'system' ? 'bg-[#f1f5f9] border-[#cbd5e1]' : 'bg-[#fcfcfc]'"
            >
              <div class="text-[10px] font-bold text-[#363e42]/40 mb-2 flex flex-wrap gap-x-2">
                <span>{{ roleLabel(m.role) }}</span>
                <span>·</span>
                <span>#{{ m.id }}</span>
                <span>·</span>
                <span>{{ fmtDateTime(m.created_at) }}</span>
              </div>
              <div class="whitespace-pre-wrap break-words">{{ m.content }}</div>
              <div v-if="m.intent_label" class="text-[10px] text-[#d97706] mt-2">
                意图：{{ intentDisplay(undefined, m.intent_label) }}
              </div>
              <details v-if="m.citations?.length" class="mt-2 text-[10px] text-[#363e42]/60">
                <summary class="cursor-pointer select-none">引用来源（{{ m.citations.length }}）</summary>
                <pre class="mt-1 p-2 bg-[#f8fafc] rounded overflow-x-auto">{{ JSON.stringify(m.citations, null, 2) }}</pre>
              </details>
            </div>
            <p v-if="!filteredMessages.length" class="text-center text-[#363e42]/40 text-sm py-12">
              {{ msgKeyword ? '无匹配消息' : '该会话暂无消息' }}
            </p>
          </template>
        </div>
      </div>

      <!-- 侧栏：数据库属性 + 上下文摘要 -->
      <aside
        v-if="selectedSessionId && sessionDetail"
        class="xl:col-span-3 bg-white rounded-2xl border flex flex-col min-h-0 min-h-[480px]"
      >
        <div class="p-4 border-b shrink-0">
          <h4 class="font-black text-sm">会话属性</h4>
          <p class="text-[10px] text-[#363e42]/45 mt-0.5">数据库字段与元数据</p>
        </div>
        <div class="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 text-[12px]">
          <dl class="space-y-2.5">
            <div class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">会话 ID</dt>
              <dd class="font-mono">{{ sessionDetail.id }}</dd>
            </div>
            <div class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">追踪 ID（context_id）</dt>
              <dd class="font-mono text-[10px] break-all text-[#363e42]/70">{{ sessionDetail.context_id }}</dd>
            </div>
            <div class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">用户 ID</dt>
              <dd>{{ sessionDetail.user_id ?? '—' }}</dd>
            </div>
            <div class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">状态</dt>
              <dd>
                <span class="inline-block px-2 py-0.5 rounded text-[10px] font-bold" :class="sessionDetail.status === 0 ? 'bg-[#363e42]/10 text-[#363e42]/60' : 'bg-emerald-50 text-emerald-700'">
                  {{ statusLabel(sessionDetail.status) }}
                </span>
              </dd>
            </div>
            <div class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">标题</dt>
              <dd>{{ sessionDetail.title }}</dd>
            </div>
            <div class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">创建时间</dt>
              <dd>{{ fmtDateTime(sessionDetail.created_at) }}</dd>
            </div>
            <div class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">最后更新</dt>
              <dd>{{ fmtDateTime(sessionDetail.updated_at) }}</dd>
            </div>
            <div class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">消息数</dt>
              <dd>{{ sessionDetail.message_count }}</dd>
            </div>
            <div v-if="sessionDetail.meta?.last_intent" class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">最近意图</dt>
              <dd>{{ intentDisplay(sessionDetail.meta.last_intent) }}</dd>
            </div>
            <div v-if="sessionDetail.meta?.note" class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">备注</dt>
              <dd class="text-[#363e42]/70">{{ sessionDetail.meta.note }}</dd>
            </div>
            <div class="flex flex-col gap-0.5">
              <dt class="text-[10px] font-bold text-[#363e42]/45 uppercase tracking-wide">置顶</dt>
              <dd>{{ sessionDetail.meta?.pinned ? '是' : '否' }}</dd>
            </div>
          </dl>

          <div v-if="previewMessages.length" class="pt-3 border-t">
            <h5 class="text-[11px] font-black text-[#363e42]/60 mb-2">上下文摘要</h5>
            <p class="text-[10px] text-[#363e42]/45 mb-3">首条与末条消息预览，完整内容见中间主面板</p>
            <div class="space-y-2">
              <div
                v-for="(m, idx) in previewMessages"
                :key="`preview-${m.id}-${idx}`"
                class="p-2.5 rounded-lg border text-[11px] bg-[#fcfcfc]"
              >
                <div class="text-[9px] font-bold text-[#363e42]/40 mb-1">
                  {{ roleLabel(m.role) }} · #{{ m.id }}
                </div>
                <div class="line-clamp-4 whitespace-pre-wrap text-[#363e42]/80">{{ m.content }}</div>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>

    <p v-if="!selectedSessionId && sessionList.length" class="text-center text-[#363e42]/35 text-[12px] mt-3">
      点击左侧会话行查看完整对话详情
    </p>
  </div>
</template>

<style scoped>
.session-history {
  max-width: 88rem;
  margin: 0 auto;
  width: 100%;
}
.session-list-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px 10px;
  flex-wrap: wrap;
}
.export-hint {
  font-size: 10px;
  color: rgba(54, 62, 66, 0.45);
}
.export-btn {
  font-size: 11px;
  font-weight: 700;
  padding: 5px 12px;
  border-radius: 8px;
  border: 1px solid rgba(54, 62, 66, 0.18);
  background: #fff;
  color: #363e42;
  cursor: pointer;
}
.export-btn:hover:not(:disabled) {
  border-color: rgba(217, 119, 6, 0.45);
  color: #d97706;
}
.export-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.close-detail-btn {
  font-size: 11px;
  color: rgba(54, 62, 66, 0.55);
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  background: #fff;
  cursor: pointer;
}
.close-detail-btn:hover {
  color: #363e42;
}
.delete-detail-btn {
  font-size: 11px;
  font-weight: 700;
  color: #dc2626;
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid rgba(239, 68, 68, 0.35);
  background: #fff;
  cursor: pointer;
}
.delete-detail-btn:hover {
  background: rgba(239, 68, 68, 0.06);
}
</style>
