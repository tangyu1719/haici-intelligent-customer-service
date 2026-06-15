<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { authHeaders } from '../api/auth'
import ListPagination from './ListPagination.vue'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'

interface PermItem { key: string; label: string }
interface ModulePerms { module_key: string; label: string; description: string; perms: PermItem[] }
interface RoleItem { id: number; code: string; name: string }
interface RolePermRow { role: RoleItem; permissions: string[] }

const modules = ref<ModulePerms[]>([])
const matrix = ref<RolePermRow[]>([])
const roles = ref<RoleItem[]>([])
const roleTotal = ref(0)
const roleQuery = ref<ListQueryState>(defaultListQuery(10))
const roleKeyword = ref('')
const loading = ref(false)
const msg = ref('')
const editRole = ref<RoleItem | null>(null)
const editPerms = ref<string[]>([])

async function loadModulesAndMatrix() {
  const [mRes, mxRes] = await Promise.all([
    fetch('/api/v1/admin/rbac/permission-modules', { headers: authHeaders() }),
    fetch('/api/v1/admin/rbac/permission-matrix', { headers: authHeaders() }),
  ])
  if (mRes.ok) modules.value = (await mRes.json()).modules || []
  if (mxRes.ok) matrix.value = (await mxRes.json()).matrix || []
}

async function loadRoles() {
  loading.value = true
  try {
    const qs = toSearchParams({
      ...roleQuery.value,
      keyword: roleKeyword.value.trim() || roleQuery.value.keyword,
    })
    const res = await fetch(`/api/v1/admin/rbac/roles/page?${qs}`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      roles.value = data.items || []
      roleTotal.value = data.total || 0
    }
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  await Promise.all([loadModulesAndMatrix(), loadRoles()])
}

function isRoleActive(role: RoleItem): boolean {
  return !!editRole.value && editRole.value.id === role.id
}

function startEditRole(role: RoleItem) {
  editRole.value = role
  const row = matrix.value.find((r) => r.role.code === role.code)
  editPerms.value = row ? [...row.permissions] : []
}

function togglePerm(key: string) {
  const i = editPerms.value.indexOf(key)
  if (i >= 0) editPerms.value.splice(i, 1)
  else editPerms.value.push(key)
}

function cancelEditRole() {
  editRole.value = null
  editPerms.value = []
}

async function saveRolePerms() {
  if (!editRole.value?.id) return
  msg.value = ''
  const r = await fetch(`/api/v1/admin/rbac/roles/${editRole.value.id}/permissions`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify({ permissions: editPerms.value }),
  })
  msg.value = r.ok ? '角色权限已保存' : '保存失败'
  if (r.ok) {
    cancelEditRole()
    await loadAll()
  }
}

function resetRoleQuery() {
  roleKeyword.value = ''
  roleQuery.value = defaultListQuery(10)
  loadRoles()
}

watch(() => [roleQuery.value.page, roleQuery.value.size], loadRoles)
onMounted(loadAll)
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-6xl mx-auto">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-lg font-black">角色权限配置</h2>
          <p class="text-[11px] text-[#64748b]">
            分页浏览角色 · 搜索筛选 · 勾选模块权限（含「查看全部用户会话」等）
          </p>
        </div>
        <span v-if="msg" class="text-[12px] font-bold" :class="msg.includes('失败') ? 'text-red-500' : 'text-green-600'">{{ msg }}</span>
      </div>

      <div class="grid grid-cols-3 gap-4">
        <!-- 左侧：角色列表（分页 + 搜索） -->
        <div class="bg-white border rounded-xl p-3 flex flex-col min-h-[480px]">
          <h3 class="text-[12px] font-bold mb-2 text-[#64748b]">角色列表</h3>
          <div class="flex gap-1 mb-2">
            <input
              v-model="roleKeyword"
              type="text"
              class="flex-1 border rounded px-2 py-1 text-[11px]"
              placeholder="搜索角色名 / code"
              @keyup.enter="loadRoles"
            />
            <button type="button" class="text-[10px] px-2 py-1 border rounded font-bold" @click="loadRoles">查</button>
            <button type="button" class="text-[10px] px-2 py-1 border rounded" @click="resetRoleQuery">重置</button>
          </div>
          <div class="flex-1 overflow-y-auto">
            <div
              v-for="r in roles"
              :key="r.id"
              class="role-list-item"
              :class="{ 'role-list-item--active': isRoleActive(r) }"
              @click="startEditRole(r)"
            >
              <div>
                <div class="text-[12px] font-bold">{{ r.name }}</div>
                <code class="text-[10px] text-[#94a3b8]">{{ r.code }}</code>
              </div>
              <span class="text-[10px] text-[#94a3b8]">
                {{ matrix.find((mx) => mx.role.code === r.code)?.permissions.length || 0 }} 项
              </span>
            </div>
            <p v-if="!roles.length && !loading" class="text-center text-[#94a3b8] text-[11px] py-6">无匹配角色</p>
            <p v-if="loading" class="text-center text-[#94a3b8] text-[11px] py-4">加载中…</p>
          </div>
          <ListPagination v-model:page="roleQuery.page" v-model:size="roleQuery.size" :total="roleTotal" />
        </div>

        <!-- 右侧：权限勾选 -->
        <div class="col-span-2 bg-white border rounded-xl p-4">
          <template v-if="editRole">
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-[13px] font-bold">编辑「{{ editRole.name }}」权限</h3>
              <div class="flex gap-2">
                <button class="bg-[#2563eb] text-white px-4 py-1.5 rounded-lg text-[11px] font-bold" @click="saveRolePerms">保存</button>
                <button class="border px-4 py-1.5 rounded-lg text-[11px]" @click="cancelEditRole">取消</button>
              </div>
            </div>
            <div class="space-y-3 max-h-[65vh] overflow-y-auto">
              <div v-for="m in modules" :key="m.module_key" class="border rounded-lg p-3">
                <div class="flex items-center gap-2 mb-2">
                  <span class="text-[11px] font-bold">{{ m.label }}</span>
                  <span class="text-[9px] text-[#94a3b8]">{{ m.description }}</span>
                  <label
                    class="ml-auto text-[10px] text-[#2563eb] cursor-pointer"
                    @click="m.perms.forEach((p) => { if (!editPerms.includes(p.key)) editPerms.push(p.key) })"
                  >全选</label>
                </div>
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-1.5">
                  <label
                    v-for="p in m.perms"
                    :key="p.key"
                    class="flex items-center gap-2 text-[11px] py-1 px-2 rounded cursor-pointer hover:bg-[#f8fafc]"
                    :class="editPerms.includes(p.key) ? 'bg-blue-50' : ''"
                  >
                    <input type="checkbox" :checked="editPerms.includes(p.key)" @change="togglePerm(p.key)" class="rounded" />
                    <span>{{ p.label }}</span>
                    <code class="text-[9px] text-[#94a3b8] ml-auto">{{ p.key }}</code>
                  </label>
                </div>
              </div>
            </div>
          </template>
          <div v-else class="text-center py-16 text-[#94a3b8] text-[12px]">从左侧选择角色，勾选其可访问的功能权限</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.role-list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
}
.role-list-item:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}
.role-list-item--active {
  background: #eff6ff;
  border-color: #2563eb;
  box-shadow: inset 3px 0 0 #2563eb;
}
</style>
