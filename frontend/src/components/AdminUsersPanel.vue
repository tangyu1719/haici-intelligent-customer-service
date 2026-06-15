<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { authHeaders } from '../api/auth'
import ListPagination from './ListPagination.vue'
import ListQueryBar from './ListQueryBar.vue'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'

interface RoleItem {
  code: string
  name: string
}

interface UserAdminItem {
  id: number
  user_no?: string
  username?: string
  email?: string
  phone?: string
  nickname: string
  status: number
  roles: string[]
  daily_questions_used: number
  daily_question_limit: number | null
  daily_questions_remaining: number | null
  daily_quota_unlimited: boolean
  created_at?: string
}

const rows = ref<UserAdminItem[]>([])
const total = ref(0)
const loading = ref(false)
const roles = ref<RoleItem[]>([])
const query = ref<ListQueryState>(defaultListQuery(20))
const statusFilter = ref('')
const roleFilter = ref('')
const quotaSettings = ref({ daily_question_limit: 100, daily_question_limit_admin: 0 })
const savingId = ref<number | null>(null)
const msg = ref('')

const sortOptions = [
  { value: 'created_at', label: '注册时间' },
  { value: 'id', label: '用户 ID' },
  { value: 'username', label: '用户名' },
]

const fmtDateTime = (s?: string): string => {
  if (!s) return '-'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN')
}

const roleLabel = (code: string): string => roles.value.find((r) => r.code === code)?.name || code

const quotaText = (row: UserAdminItem): string => {
  if (row.daily_quota_unlimited) return `${row.daily_questions_used} / 不限`
  const limit = row.daily_question_limit ?? quotaSettings.value.daily_question_limit
  return `${row.daily_questions_used} / ${limit}（剩 ${row.daily_questions_remaining ?? 0}）`
}

const loadRoles = async (): Promise<void> => {
  const res = await fetch('/api/v1/admin/rbac/roles', { headers: authHeaders() })
  if (res.ok) roles.value = await res.json()
}

const loadQuotaSettings = async (): Promise<void> => {
  const res = await fetch('/api/v1/admin/rbac/quota-settings', { headers: authHeaders() })
  if (res.ok) quotaSettings.value = await res.json()
}

const loadUsers = async (): Promise<void> => {
  loading.value = true
  msg.value = ''
  try {
    const qs = toSearchParams(query.value, {
      status: statusFilter.value !== '' ? statusFilter.value : undefined,
      role: roleFilter.value || undefined,
    })
    const res = await fetch(`/api/v1/admin/rbac/users?${qs}`, { headers: authHeaders() })
    if (!res.ok) {
      msg.value = `加载失败（HTTP ${res.status}）`
      return
    }
    const data = await res.json()
    rows.value = data.items || []
    total.value = data.total || 0
    if (data.page) query.value.page = data.page
    if (data.size) query.value.size = data.size
  } finally {
    loading.value = false
  }
}

const resetQuery = (): void => {
  query.value = defaultListQuery(20)
  statusFilter.value = ''
  roleFilter.value = ''
  loadUsers()
}

const toggleRole = async (row: UserAdminItem, roleCode: string): Promise<void> => {
  const next = new Set(row.roles)
  if (next.has(roleCode)) next.delete(roleCode)
  else next.add(roleCode)
  if (!next.size) next.add('viewer')
  await saveRoles(row.id, [...next])
}

const saveRoles = async (userId: number, roleCodes: string[]): Promise<void> => {
  savingId.value = userId
  msg.value = ''
  try {
    const res = await fetch(`/api/v1/admin/rbac/users/${userId}/roles`, {
      method: 'PUT',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ roles: roleCodes }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      msg.value = typeof data.detail === 'string' ? data.detail : '角色更新失败'
      return
    }
    const idx = rows.value.findIndex((r) => r.id === userId)
    if (idx >= 0) rows.value[idx] = data
    msg.value = '角色已更新'
  } finally {
    savingId.value = null
  }
}

const toggleStatus = async (row: UserAdminItem): Promise<void> => {
  const next = row.status === 1 ? 0 : 1
  if (!window.confirm(next === 0 ? `确定禁用用户 ${row.nickname || row.username || row.id}？` : '确定启用该用户？')) return
  savingId.value = row.id
  msg.value = ''
  try {
    const res = await fetch(`/api/v1/admin/rbac/users/${row.id}/status`, {
      method: 'PATCH',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: next }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      msg.value = typeof data.detail === 'string' ? data.detail : '状态更新失败'
      return
    }
    const idx = rows.value.findIndex((r) => r.id === row.id)
    if (idx >= 0) rows.value[idx] = data
    msg.value = next === 1 ? '用户已启用' : '用户已禁用'
  } finally {
    savingId.value = null
  }
}

watch(() => [query.value.page, query.value.size], loadUsers)

onMounted(async () => {
  await Promise.all([loadRoles(), loadQuotaSettings()])
  await loadUsers()
})
</script>

<template>
  <div class="admin-users-panel">
    <header class="panel-hd">
      <div>
        <h2 class="panel-title">用户权限管理</h2>
        <p class="panel-sub">
          普通用户每日提问上限 <strong>{{ quotaSettings.daily_question_limit }}</strong> 次（环境变量
          <code>DAILY_QUESTION_LIMIT</code>）；
          管理员默认
          <strong>{{ quotaSettings.daily_question_limit_admin <= 0 ? '不限次' : quotaSettings.daily_question_limit_admin + ' 次' }}</strong>
          （<code>DAILY_QUESTION_LIMIT_ADMIN</code>）
        </p>
      </div>
    </header>

    <ListQueryBar
      v-model="query"
      :sort-options="sortOptions"
      name-placeholder="用户名"
      keyword-placeholder="用户名/邮箱/手机/昵称"
      @search="loadUsers"
      @reset="resetQuery"
    />

    <div class="filter-row">
      <label>
        状态
        <select v-model="statusFilter" class="filter-select" @change="query.page = 1; loadUsers()">
          <option value="">全部</option>
          <option value="1">启用</option>
          <option value="0">禁用</option>
        </select>
      </label>
      <label>
        角色
        <select v-model="roleFilter" class="filter-select" @change="query.page = 1; loadUsers()">
          <option value="">全部</option>
          <option v-for="r in roles" :key="r.code" :value="r.code">{{ r.name }}（{{ r.code }}）</option>
        </select>
      </label>
    </div>

    <p v-if="msg" class="panel-msg">{{ msg }}</p>

    <div class="table-wrap">
      <table class="users-table">
        <thead>
          <tr>
            <th>用户</th>
            <th>账号</th>
            <th>状态</th>
            <th>角色（RBAC）</th>
            <th>今日提问</th>
            <th>注册时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="7" class="empty-cell">加载中…</td>
          </tr>
          <tr v-else-if="!rows.length">
            <td colspan="7" class="empty-cell">暂无用户</td>
          </tr>
          <tr v-for="row in rows" :key="row.id">
            <td>
              <div class="user-name">{{ row.nickname || '—' }}</div>
              <div class="user-no">#{{ row.user_no || row.id }}</div>
            </td>
            <td>
              <div v-if="row.username">{{ row.username }}</div>
              <div v-if="row.email" class="muted">{{ row.email }}</div>
              <div v-if="row.phone" class="muted">{{ row.phone }}</div>
            </td>
            <td>
              <span class="status-badge" :class="row.status === 1 ? 'on' : 'off'">
                {{ row.status === 1 ? '启用' : '禁用' }}
              </span>
            </td>
            <td>
              <div class="role-chips">
                <button
                  v-for="r in roles"
                  :key="row.id + '-' + r.code"
                  type="button"
                  class="role-chip"
                  :class="{ active: row.roles.includes(r.code), saving: savingId === row.id }"
                  :disabled="savingId === row.id"
                  @click="toggleRole(row, r.code)"
                >
                  {{ r.name }}
                </button>
              </div>
            </td>
            <td>{{ quotaText(row) }}</td>
            <td>{{ fmtDateTime(row.created_at) }}</td>
            <td>
              <button
                type="button"
                class="action-btn"
                :disabled="savingId === row.id"
                @click="toggleStatus(row)"
              >
                {{ row.status === 1 ? '禁用' : '启用' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ListPagination v-model:page="query.page" v-model:size="query.size" :total="total" @change="loadUsers" />
  </div>
</template>

<style scoped>
.admin-users-panel {
  max-width: 1200px;
  margin: 0 auto;
}
.panel-hd {
  margin-bottom: 16px;
}
.panel-title {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: #363e42;
}
.panel-sub {
  margin: 6px 0 0;
  font-size: 12px;
  color: #64748b;
  line-height: 1.6;
}
.panel-sub code {
  font-size: 11px;
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 4px;
}
.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin: 12px 0;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}
.filter-select {
  margin-left: 6px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  border-radius: 8px;
  padding: 4px 8px;
  font-size: 12px;
}
.panel-msg {
  margin: 8px 0;
  font-size: 12px;
  color: #2563eb;
  font-weight: 600;
}
.table-wrap {
  overflow-x: auto;
  background: #fff;
  border: 1px solid rgba(54, 62, 66, 0.08);
  border-radius: 16px;
}
.users-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.users-table th,
.users-table td {
  padding: 12px 14px;
  text-align: left;
  border-bottom: 1px solid rgba(54, 62, 66, 0.06);
  vertical-align: top;
}
.users-table th {
  background: #fcfcfc;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}
.user-name {
  font-weight: 700;
  color: #363e42;
}
.user-no {
  font-size: 10px;
  color: #94a3b8;
  font-family: ui-monospace, monospace;
}
.muted {
  color: #64748b;
  font-size: 11px;
}
.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
}
.status-badge.on {
  background: #ecfdf5;
  color: #059669;
}
.status-badge.off {
  background: #fef2f2;
  color: #dc2626;
}
.role-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.role-chip {
  font-size: 10px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  background: #f8fafc;
  color: #64748b;
  cursor: pointer;
}
.role-chip.active {
  border-color: rgba(37, 99, 235, 0.35);
  background: rgba(37, 99, 235, 0.1);
  color: #1d4ed8;
}
.role-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.action-btn {
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  background: #fff;
  cursor: pointer;
}
.action-btn:hover {
  border-color: rgba(217, 119, 6, 0.35);
  color: #d97706;
}
.empty-cell {
  text-align: center;
  color: #94a3b8;
  padding: 24px;
}
</style>
