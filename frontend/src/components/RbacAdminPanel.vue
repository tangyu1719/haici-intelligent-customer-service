<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface PermItem { key: string; label: string }
interface ModulePerms { module_key: string; label: string; icon: string; description: string; perms: PermItem[] }
interface RoleItem { id: number; code: string; name: string }
interface RolePermRow { role: RoleItem; permissions: string[] }
interface UserItem { user_id: number; user_no: string; username: string; nickname: string; roles: {code:string;name:string}[] }

const modules = ref<ModulePerms[]>([])
const roles = ref<RoleItem[]>([])
const matrix = ref<RolePermRow[]>([])
const users = ref<UserItem[]>([])
const tab = ref<'modules'|'matrix'|'users'>('modules')
const msg = ref('')

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

function hasPerm(roleCode: string, permKey: string): boolean {
  const row = matrix.value.find(r => r.role.code === roleCode)
  return row ? row.permissions.includes(permKey) : false
}

async function assignRole(userId: number, roleCode: string) {
  msg.value = ''
  const r = await fetch(`/api/v1/admin/rbac/users/${userId}/roles`, {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ roles: [roleCode] }),
  })
  msg.value = r.ok ? '角色已更新' : '更新失败'
  if (r.ok) await loadAll()
}

onMounted(loadAll)
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-6xl mx-auto">
      <h2 class="text-lg font-black mb-1">用户权限</h2>
      <p class="text-[11px] text-[#64748b] mb-4">按业务模块查看权限定义、角色-权限矩阵、用户角色分配</p>
      <p v-if="msg" class="text-[12px] mb-3" :class="msg.includes('失败')?'text-red-500':'text-green-600'">{{ msg }}</p>

      <div class="flex gap-0 mb-4 border-b">
        <button v-for="t in [{k:'modules',l:'权限模块'},{k:'matrix',l:'角色权限矩阵'},{k:'users',l:'用户角色'}]" :key="t.k"
          class="px-4 py-2 text-[12px] font-bold border-b-2 transition-colors"
          :class="tab===t.k?'border-[#2563eb] text-[#1d4ed8]':'border-transparent text-[#64748b]'"
          @click="tab=t.k as any">{{ t.l }}</button>
      </div>

      <!-- 权限模块 -->
      <div v-if="tab==='modules'" class="space-y-4">
        <div v-for="m in modules" :key="m.module_key" class="bg-white border rounded-xl p-4">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-[14px] font-bold">{{ m.label }}</span>
            <span class="text-[10px] text-[#94a3b8]">{{ m.description }}</span>
          </div>
          <div class="grid grid-cols-3 gap-2">
            <div v-for="p in m.perms" :key="p.key"
              class="flex items-center gap-2 text-[12px] py-1.5 px-3 bg-[#f8fafc] rounded-lg">
              <code class="text-[10px] bg-[#f1f5f9] px-1.5 py-0.5 rounded font-mono text-[#64748b]">{{ p.key }}</code>
              <span class="text-[#363e42]">{{ p.label }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 角色权限矩阵 -->
      <div v-if="tab==='matrix'" class="bg-white border rounded-xl overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-[11px]">
            <thead class="bg-[#f8fafc] text-[#94a3b8]">
              <tr>
                <th class="p-3 text-left w-[100px]">权限 \\ 角色</th>
                <th v-for="r in roles" :key="r.id" class="p-3 text-center w-[80px]">{{ r.name }}</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="m in modules" :key="m.module_key">
                <tr class="bg-[#f8fafc]"><td colspan="99" class="p-2 text-[10px] font-bold text-[#64748b]">{{ m.label }} — {{ m.description }}</td></tr>
                <tr v-for="p in m.perms" :key="p.key" class="border-t hover:bg-[#f8fafc]">
                  <td class="p-2">
                    <div class="font-bold">{{ p.label }}</div>
                    <code class="text-[9px] text-[#94a3b8]">{{ p.key }}</code>
                  </td>
                  <td v-for="r in roles" :key="r.id" class="p-2 text-center">
                    <span v-if="hasPerm(r.code, p.key)" class="text-green-500 font-bold">✓</span>
                    <span v-else class="text-[#d1d5db]">—</span>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 用户角色 -->
      <div v-if="tab==='users'" class="bg-white border rounded-xl overflow-hidden">
        <table class="w-full text-[12px]">
          <thead class="bg-[#f8fafc] text-[#94a3b8]">
            <tr>
              <th class="p-3 text-left">用户</th>
              <th class="p-3 text-left">编号</th>
              <th class="p-3 text-left">当前角色</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.user_id" class="border-t hover:bg-[#f8fafc]">
              <td class="p-3">
                <span class="font-bold">{{ u.nickname || u.username || u.user_no }}</span>
                <span v-if="u.email" class="text-[10px] text-[#94a3b8] ml-2">{{ u.email }}</span>
              </td>
              <td class="p-3 font-mono text-[11px] text-[#64748b]">{{ u.user_no }}</td>
              <td class="p-3">
                <span v-for="r in u.roles" :key="r.code"
                  class="inline-block text-[10px] px-2 py-0.5 rounded-full font-bold mr-1"
                  :class="r.code==='admin'?'bg-red-100 text-red-600':'bg-blue-100 text-blue-600'">{{ r.name }}</span>
                <span v-if="!u.roles.length" class="text-[#94a3b8]">无角色</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
