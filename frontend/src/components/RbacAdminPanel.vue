<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface PermItem { key: string; label: string }
interface ModulePerms { module_key: string; label: string; description: string; perms: PermItem[] }
interface RoleItem { id?: number; code: string; name: string }
interface RolePermRow { role: RoleItem; permissions: string[] }
interface UserItem { user_id: number; user_no: string; username: string; nickname: string; email: string; roles: {code:string;name:string}[]; daily_used?: number; daily_limit?: number }

const modules = ref<ModulePerms[]>([])
const roles = ref<RoleItem[]>([])
const matrix = ref<RolePermRow[]>([])
const users = ref<UserItem[]>([])
const tab = ref<'users'|'roles'>('users')
const msg = ref('')
const editRole = ref<RoleItem|null>(null)
const editPerms = ref<string[]>([])
const quotaLimit = ref(100)

async function loadAll() {
  const [mRes, rRes, mxRes, uRes] = await Promise.all([
    fetch('/api/v1/admin/rbac/permission-modules', { headers: authHeaders() }),
    fetch('/api/v1/admin/rbac/roles', { headers: authHeaders() }),
    fetch('/api/v1/admin/rbac/permission-matrix', { headers: authHeaders() }),
    fetch('/api/v1/admin/rbac/users?page=1&size=100', { headers: authHeaders() }),
  ])
  if (mRes.ok) modules.value = (await mRes.json()).modules || []
  if (rRes.ok) roles.value = (await rRes.json()) || []
  if (mxRes.ok) matrix.value = (await mxRes.json()).matrix || []
  if (uRes.ok) users.value = (await uRes.json()).users || []
}

// ── 角色权限编辑 ──
function isRoleActive(role: RoleItem): boolean {
  return !!editRole.value && editRole.value.code === role.code
}

function startEditRole(role: RoleItem) {
  editRole.value = role
  const row = matrix.value.find(r => r.role.code === role.code)
  editPerms.value = row ? [...row.permissions] : []
}
function togglePerm(key: string) {
  const i = editPerms.value.indexOf(key)
  if (i >= 0) editPerms.value.splice(i, 1)
  else editPerms.value.push(key)
}
function cancelEditRole() { editRole.value = null; editPerms.value = [] }
async function saveRolePerms() {
  if (!editRole.value) return
  const target = roles.value.find((r) => r.code === editRole.value!.code) || editRole.value
  if (!target?.id) {
    msg.value = '保存失败：角色 ID 无效'
    return
  }
  msg.value = ''
  const r = await fetch(`/api/v1/admin/rbac/roles/${target.id}/permissions`, {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ permissions: editPerms.value }),
  })
  msg.value = r.ok ? '角色权限已保存' : '保存失败'
  if (r.ok) { cancelEditRole(); await loadAll() }
}

// ── 用户角色 ──
async function setUserRole(userId: number, roleCode: string) {
  msg.value = ''
  const r = await fetch(`/api/v1/admin/rbac/users/${userId}/roles`, {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ roles: [roleCode] }),
  })
  msg.value = r.ok ? '已更新' : '更新失败'
  if (r.ok) await loadAll()
}

// ── 配额 ──
async function setUserQuota(userId: number) {
  msg.value = ''
  const r = await fetch(`/api/v1/admin/rbac/users/${userId}/quota`, {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ daily_limit: quotaLimit.value }),
  })
  msg.value = r.ok ? `配额已设为${quotaLimit.value}` : '设置失败'
}

onMounted(loadAll)
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-6xl mx-auto">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-lg font-black">用户权限</h2>
          <p class="text-[11px] text-[#64748b]">用户管理 · 角色管理 · 权限配置 · 每日提问上限</p>
        </div>
        <span v-if="msg" class="text-[12px] font-bold" :class="msg.includes('失败')?'text-red-500':'text-green-600'">{{ msg }}</span>
      </div>

      <div class="flex gap-0 mb-4 border-b">
        <button class="px-5 py-2.5 text-[12px] font-bold border-b-2 transition-colors"
          :class="tab==='users'?'border-[#2563eb] text-[#1d4ed8]':'border-transparent text-[#64748b]'"
          @click="tab='users'">用户管理</button>
        <button class="px-5 py-2.5 text-[12px] font-bold border-b-2 transition-colors"
          :class="tab==='roles'?'border-[#2563eb] text-[#1d4ed8]':'border-transparent text-[#64748b]'"
          @click="tab='roles'">角色管理</button>
      </div>

      <!-- ═══ 用户管理 ═══ -->
      <div v-if="tab==='users'" class="bg-white border rounded-xl overflow-hidden">
        <table class="w-full text-[12px]">
          <thead class="bg-[#f8fafc] text-[#94a3b8]">
            <tr>
              <th class="p-3 text-left">用户</th>
              <th class="p-3 text-left">编号</th>
              <th class="p-3 text-left">邮箱</th>
              <th class="p-3 text-left w-[180px]">角色</th>
              <th class="p-3 text-left w-[120px]">每日提问上限</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.user_id" class="border-t hover:bg-[#f8fafc]">
              <td class="p-3">
                <span class="font-bold">{{ u.nickname || u.username || u.user_no }}</span>
              </td>
              <td class="p-3 font-mono text-[11px] text-[#64748b]">{{ u.user_no }}</td>
              <td class="p-3 text-[11px] text-[#64748b]">{{ u.email || '-' }}</td>
              <td class="p-3">
                <select class="border rounded px-2 py-1 text-[11px]"
                  @change="setUserRole(u.user_id, ($event.target as HTMLSelectElement).value)">
                  <option value="">选择角色...</option>
                  <option v-for="r in roles" :key="r.id" :value="r.code"
                    :selected="u.roles?.some(ur=>ur.code===r.code)">{{ r.name }}</option>
                </select>
                <span v-for="r in (u.roles||[])" :key="r.code"
                  class="ml-1 text-[9px] px-1.5 py-0.5 rounded-full font-bold"
                  :class="r.code==='admin'?'bg-red-100 text-red-600':'bg-blue-100 text-blue-600'">{{ r.name }}</span>
              </td>
              <td class="p-3">
                <div class="flex items-center gap-1">
                  <input v-model.number="quotaLimit" type="number" class="border rounded px-2 py-1 text-[11px] w-16" min="0" max="9999" />
                  <button class="text-[10px] bg-[#2563eb] text-white px-2 py-1 rounded font-bold" @click="setUserQuota(u.user_id)">设置</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ═══ 角色管理 ═══ -->
      <div v-if="tab==='roles'" class="grid grid-cols-3 gap-4">
        <!-- 左侧角色列表 -->
        <div class="bg-white border rounded-xl p-3">
          <h3 class="text-[12px] font-bold mb-3 text-[#64748b]">角色列表</h3>
          <div
            v-for="r in roles"
            :key="r.code"
            class="role-list-item"
            :class="{ 'role-list-item--active': isRoleActive(r) }"
            @click="startEditRole(r)"
          >
            <div>
              <div class="text-[12px] font-bold">{{ r.name }}</div>
              <code class="text-[10px] text-[#94a3b8]">{{ r.code }}</code>
            </div>
            <span class="text-[10px] text-[#94a3b8]">{{ matrix.find(mx=>mx.role.code===r.code)?.permissions.length||0 }}项权限</span>
          </div>
        </div>

        <!-- 右侧权限勾选 -->
        <div class="col-span-2 bg-white border rounded-xl p-4">
          <template v-if="editRole">
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-[13px] font-bold">编辑「{{ editRole.name }}」权限</h3>
              <div class="flex gap-2">
                <button class="bg-[#2563eb] text-white px-4 py-1.5 rounded-lg text-[11px] font-bold" @click="saveRolePerms">保存</button>
                <button class="border px-4 py-1.5 rounded-lg text-[11px]" @click="cancelEditRole">取消</button>
              </div>
            </div>
            <div class="space-y-3 max-h-[60vh] overflow-y-auto">
              <div v-for="m in modules" :key="m.module_key" class="border rounded-lg p-3">
                <div class="flex items-center gap-2 mb-2">
                  <span class="text-[11px] font-bold">{{ m.label }}</span>
                  <span class="text-[9px] text-[#94a3b8]">{{ m.description }}</span>
                  <label class="ml-auto text-[10px] text-[#2563eb] cursor-pointer" @click="m.perms.forEach(p=>{if(!editPerms.includes(p.key))editPerms.push(p.key)})">全选</label>
                </div>
                <div class="grid grid-cols-2 gap-1.5">
                  <label v-for="p in m.perms" :key="p.key"
                    class="flex items-center gap-2 text-[11px] py-1 px-2 rounded cursor-pointer hover:bg-[#f8fafc]"
                    :class="editPerms.includes(p.key)?'bg-blue-50':''">
                    <input type="checkbox" :checked="editPerms.includes(p.key)" @change="togglePerm(p.key)" class="rounded" />
                    <span>{{ p.label }}</span>
                    <code class="text-[9px] text-[#94a3b8] ml-auto">{{ p.key }}</code>
                  </label>
                </div>
              </div>
            </div>
          </template>
          <div v-else class="text-center py-16 text-[#94a3b8] text-[12px]">点击左侧角色编辑其权限</div>
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

.role-list-item--active:hover {
  background: #eff6ff;
}
</style>
