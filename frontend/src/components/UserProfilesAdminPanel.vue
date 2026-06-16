<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'
import ListPagination from './ListPagination.vue'
import ListQueryBar from './ListQueryBar.vue'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'

interface ProfileListItem {
  user_id: number
  user_no?: string
  username?: string
  nickname: string
  has_profile: boolean
  profile_chars: number
}

const rows = ref<ProfileListItem[]>([])
const total = ref(0)
const loading = ref(false)
const query = ref<ListQueryState>(defaultListQuery(20))
const selectedId = ref<number | null>(null)
const detailMd = ref('')
const detailTitle = ref('')
const detailLoading = ref(false)
const editing = ref(false)
const saving = ref(false)
const msg = ref('')

const sortOptions = [
  { value: 'id', label: '用户 ID' },
  { value: 'username', label: '用户名' },
  { value: 'created_at', label: '注册时间' },
]

const loadList = async (): Promise<void> => {
  loading.value = true
  msg.value = ''
  try {
    const params = toSearchParams(query.value)
    const res = await fetch(`/api/v1/admin/user-profiles?${params}`, { headers: authHeaders() })
    if (!res.ok) {
      msg.value = '加载用户画像列表失败'
      return
    }
    const data = await res.json()
    rows.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const loadDetail = async (userId: number): Promise<void> => {
  selectedId.value = userId
  detailLoading.value = true
  editing.value = false
  detailMd.value = ''
  msg.value = ''
  try {
    const res = await fetch(`/api/v1/admin/user-profiles/${userId}`, { headers: authHeaders() })
    if (!res.ok) {
      detailMd.value = '加载失败'
      return
    }
    const data = await res.json()
    detailTitle.value = `${data.nickname || data.username || data.user_no || data.user_id} 的画像`
    detailMd.value = data.markdown || ''
  } finally {
    detailLoading.value = false
  }
}

const startEdit = (): void => {
  editing.value = true
  msg.value = ''
}

const cancelEdit = async (): Promise<void> => {
  if (selectedId.value != null) await loadDetail(selectedId.value)
  else editing.value = false
}

const saveDetail = async (): Promise<void> => {
  if (selectedId.value == null) return
  saving.value = true
  msg.value = ''
  try {
    const res = await fetch(`/api/v1/admin/user-profiles/${selectedId.value}`, {
      method: 'PUT',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ markdown: detailMd.value }),
    })
    const data = await res.json()
    if (!res.ok) {
      msg.value = typeof data.detail === 'string' ? data.detail : '保存失败'
      return
    }
    detailMd.value = data.markdown || ''
    detailTitle.value = `${data.nickname || data.username || data.user_no || data.user_id} 的画像`
    editing.value = false
    msg.value = '保存成功'
    await loadList()
  } finally {
    saving.value = false
  }
}

onMounted(loadList)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-bold text-[#363e42]">用户 MD 画像</h2>
      <p class="text-xs text-[#363e42]/50">管理员可编辑任意用户画像；5 星反馈沉淀原子事实</p>
    </div>

    <ListQueryBar
      v-model:keyword="query.keyword"
      v-model:sort-by="query.sort_by"
      v-model:sort-order="query.sort_order"
      :sort-options="sortOptions"
      placeholder="搜索用户名/昵称/用户号"
      @search="loadList"
    />

    <p v-if="msg" class="text-sm" :class="msg === '保存成功' ? 'text-green-600' : 'text-red-500'">{{ msg }}</p>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-[420px]">
      <div class="bg-white border rounded-xl overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-[#f8f9fa] text-[#363e42]/60">
            <tr>
              <th class="p-3 text-left">用户</th>
              <th class="p-3 text-left">画像</th>
              <th class="p-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td colspan="3" class="p-6 text-center text-[#363e42]/40">加载中…</td>
            </tr>
            <tr
              v-for="row in rows"
              :key="row.user_id"
              class="border-t hover:bg-[#fafafa]"
              :class="selectedId === row.user_id ? 'bg-[#f0f7ff]' : ''"
            >
              <td class="p-3">
                <div class="font-medium">{{ row.nickname || row.username || '-' }}</div>
                <div class="text-xs text-[#363e42]/50">{{ row.user_no || row.user_id }}</div>
              </td>
              <td class="p-3">
                <span v-if="row.has_profile" class="text-green-600">{{ row.profile_chars }} 字</span>
                <span v-else class="text-[#363e42]/40">暂无</span>
              </td>
              <td class="p-3 text-right">
                <button
                  type="button"
                  class="text-[#2563eb] text-xs font-bold"
                  @click="loadDetail(row.user_id)"
                >
                  查看
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <ListPagination v-model:page="query.page" v-model:size="query.size" :total="total" @update:page="loadList" @update:size="loadList" />
      </div>

      <div class="bg-white border rounded-xl p-4 flex flex-col min-h-[420px] max-h-[520px]">
        <div class="flex items-center justify-between gap-2 mb-3 shrink-0">
          <h3 class="text-sm font-bold">{{ detailTitle || '选择用户查看画像' }}</h3>
          <div v-if="selectedId != null && !detailLoading" class="flex gap-2">
            <button
              v-if="!editing"
              type="button"
              class="text-xs font-bold text-[#2563eb]"
              @click="startEdit"
            >
              编辑
            </button>
            <template v-else>
              <button type="button" class="text-xs font-bold text-[#363e42]/60" @click="cancelEdit">取消</button>
              <button
                type="button"
                class="text-xs font-bold text-white bg-[#363e42] px-3 py-1 rounded-lg disabled:opacity-50"
                :disabled="saving"
                @click="saveDetail"
              >
                {{ saving ? '保存中…' : '保存' }}
              </button>
            </template>
          </div>
        </div>
        <p v-if="detailLoading" class="text-sm text-[#363e42]/40">加载中…</p>
        <textarea
          v-else-if="editing"
          v-model="detailMd"
          class="flex-1 w-full border rounded-lg p-3 text-xs font-mono leading-relaxed resize-none"
        />
        <pre v-else class="flex-1 text-xs whitespace-pre-wrap leading-relaxed text-[#363e42]/80 font-sans overflow-y-auto">{{ detailMd || '（左侧点击「查看」）' }}</pre>
      </div>
    </div>
  </div>
</template>
