<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { authHeaders } from '../api/auth'
import type { AdminChatSessionItem, ChatMessageItem } from '../types'
import ListPagination from './ListPagination.vue'
import ListQueryBar from './ListQueryBar.vue'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'
import { intentDisplay } from '../utils/intentLabels'

const rows = ref<AdminChatSessionItem[]>([])
const total = ref(0)
const loading = ref(false)
const query = ref<ListQueryState>({ ...defaultListQuery(20), sortBy: 'updated_at', sortOrder: 'desc' })
const filterUserId = ref('')
const filterUserDeleted = ref('')
const selectedId = ref<number | null>(null)
const detail = ref<AdminChatSessionItem | null>(null)
const messages = ref<ChatMessageItem[]>([])
const msgLoading = ref(false)

const fmtDateTime = (s?: string | null): string => {
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

const userLabel = (row: AdminChatSessionItem): string =>
  row.nickname || row.username || `用户 #${row.user_id}`

const loadList = async (): Promise<void> => {
  loading.value = true
  try {
    const qs = toSearchParams(query.value, {
      user_id: filterUserId.value || undefined,
      user_deleted: filterUserDeleted.value !== '' ? filterUserDeleted.value : undefined,
    })
    const res = await fetch(`/api/v1/admin/sessions?${qs}`, { headers: authHeaders() })
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
  query.value = { ...defaultListQuery(20), sortBy: 'updated_at', sortOrder: 'desc' }
  filterUserId.value = ''
  filterUserDeleted.value = ''
  loadList()
}

const loadAllMessages = async (sessionId: number, totalHint?: number): Promise<void> => {
  msgLoading.value = true
  try {
    const all: ChatMessageItem[] = []
    let page = 1
    const size = 100
    let totalCount = totalHint || 0
    while (true) {
      const qs = toSearchParams({ ...defaultListQuery(size), page, size, sortBy: 'created_at', sortOrder: 'asc' })
      const res = await fetch(`/api/v1/admin/sessions/${sessionId}/messages?${qs}`, { headers: authHeaders() })
      if (!res.ok) break
      const data = await res.json()
      const batch: ChatMessageItem[] = data.items || []
      all.push(...batch)
      totalCount = data.total ?? totalCount
      if (!batch.length || all.length >= totalCount) break
      page += 1
    }
    messages.value = all
  } finally {
    msgLoading.value = false
  }
}

const openDetail = async (row: AdminChatSessionItem): Promise<void> => {
  selectedId.value = row.id
  messages.value = []
  const res = await fetch(`/api/v1/admin/sessions/${row.id}`, { headers: authHeaders() })
  if (res.ok) {
    detail.value = await res.json()
    await loadAllMessages(row.id, detail.value?.message_count)
  }
}

const closeDetail = (): void => {
  selectedId.value = null
  detail.value = null
  messages.value = []
}

watch(() => [query.value.page, query.value.size], loadList)
onMounted(loadList)
</script>

<template>
  <div class="admin-sessions flex flex-col min-h-0 h-full max-w-[88rem] mx-auto w-full">
    <p class="text-[12px] text-[#363e42]/55 mb-4">
      管理员可查看全部用户会话，包含用户已在「智能对话 / 会话历史」中删除的记录（软删除，数据仍保留）。
    </p>
    <div class="flex-1 min-h-0 grid gap-4" :class="selectedId ? 'grid-cols-1 xl:grid-cols-12' : 'grid-cols-1'">
      <div class="bg-white rounded-2xl border overflow-hidden flex flex-col min-h-0" :class="selectedId ? 'xl:col-span-5' : ''">
        <ListQueryBar
          v-model="query"
          :sort-options="[
            { value: 'updated_at', label: '最后更新' },
            { value: 'created_at', label: '创建时间' },
            { value: 'id', label: '会话 ID' },
            { value: 'user_id', label: '用户 ID' },
          ]"
          name-placeholder="标题 / 用户名 / 昵称"
          keyword-placeholder="标题 / 追踪 ID"
          @search="loadList"
          @reset="resetQuery"
        />
        <div class="px-3 pb-3 flex flex-wrap gap-2 items-center text-[11px]">
          <input v-model="filterUserId" type="text" placeholder="用户 ID" class="border rounded px-2 py-1 w-24" />
          <select v-model="filterUserDeleted" class="border rounded px-2 py-1">
            <option value="">全部删除状态</option>
            <option value="0">用户未删除</option>
            <option value="1">用户已删除</option>
          </select>
          <button type="button" class="export-btn" @click="loadList">筛选</button>
          <span v-if="loading" class="text-[#363e42]/45">加载中…</span>
        </div>
        <div class="flex-1 min-h-0 overflow-y-auto">
          <table class="w-full text-sm">
            <thead class="bg-[#fcfcfc] text-[#363e42]/60 text-[11px] sticky top-0">
              <tr>
                <th class="p-3 text-left">ID</th>
                <th class="p-3 text-left">用户</th>
                <th class="p-3 text-left">标题</th>
                <th class="p-3 text-left">更新</th>
                <th class="p-3 text-left">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.id"
                class="border-t cursor-pointer hover:bg-[#fdf6e3]/30"
                :class="selectedId === row.id ? 'bg-[#d97706]/10' : ''"
                @click="openDetail(row)"
              >
                <td class="p-3 font-mono text-[11px]">#{{ row.id }}</td>
                <td class="p-3 text-[11px]">
                  <div class="font-bold">{{ userLabel(row) }}</div>
                  <div class="text-[#363e42]/45">UID {{ row.user_id }}</div>
                </td>
                <td class="p-3 text-[12px] font-bold max-w-[180px] truncate" :title="row.title">{{ row.title || '新对话' }}</td>
                <td class="p-3 text-[11px] whitespace-nowrap">{{ fmtDateTime(row.updated_at) }}</td>
                <td class="p-3 text-[10px]">
                  <span
                    v-if="row.user_deleted"
                    class="inline-block px-2 py-0.5 rounded bg-red-50 text-red-600 font-bold"
                    :title="fmtDateTime(row.user_deleted_at)"
                  >
                    用户已删
                  </span>
                  <span v-else class="inline-block px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 font-bold">正常</span>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="!rows.length && !loading" class="p-8 text-center text-[#363e42]/40 text-sm">暂无会话记录</p>
        </div>
        <ListPagination v-model:page="query.page" v-model:size="query.size" :total="total" />
      </div>

      <div v-if="selectedId && detail" class="xl:col-span-7 bg-white rounded-2xl border flex flex-col min-h-0">
        <div class="p-4 border-b flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h3 class="font-black text-base truncate">{{ detail.title }}</h3>
            <p class="text-[11px] text-[#363e42]/50 mt-1">
              会话 #{{ detail.id }} · {{ userLabel(detail) }} · {{ messages.length }} 条消息
            </p>
            <p v-if="detail.user_deleted" class="text-[11px] text-red-500 mt-1">
              用户已于 {{ fmtDateTime(detail.user_deleted_at) }} 从界面删除（管理员仍可查看）
            </p>
          </div>
          <button type="button" class="close-detail-btn" @click="closeDetail">关闭</button>
        </div>
        <div class="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
          <p v-if="msgLoading" class="text-center text-[#363e42]/40 text-sm py-8">加载对话中…</p>
          <div
            v-for="m in messages"
            :key="m.id"
            class="p-3 rounded-xl border text-[13px]"
            :class="m.role === 'user' ? 'bg-[#d97706]/10 border-[#d97706]/20' : 'bg-[#fcfcfc]'"
          >
            <div class="text-[10px] text-[#363e42]/40 mb-1">{{ m.role === 'user' ? '用户' : '助手' }} · #{{ m.id }} · {{ fmtDateTime(m.created_at) }}</div>
            <div class="whitespace-pre-wrap break-words">{{ m.content }}</div>
            <div v-if="m.intent_label" class="text-[10px] text-[#d97706] mt-1">意图：{{ intentDisplay(undefined, m.intent_label) }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.export-btn {
  font-size: 11px;
  font-weight: 700;
  padding: 5px 12px;
  border-radius: 8px;
  border: 1px solid rgba(54, 62, 66, 0.18);
  background: #fff;
  cursor: pointer;
}
.close-detail-btn {
  font-size: 11px;
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  background: #fff;
  cursor: pointer;
}
</style>
