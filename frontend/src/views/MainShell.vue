<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authHeaders, clearAuth, currentUser, getAccessToken, hasPerm, loadAuthFromStorage } from '../api/auth'
import type { KnowledgeBaseBrief, KnowledgeDoc } from '../types'
import AgentConfigPanel from '../components/AgentConfigPanel.vue'
import GatewayPanel from '../components/GatewayPanel.vue'
import ChatPanel from '../components/ChatPanel.vue'
import EvalDashboard from '../components/EvalDashboard.vue'
import FeedbackAdminPanel from '../components/FeedbackAdminPanel.vue'
import AdminUsersPanel from '../components/AdminUsersPanel.vue'
import ListPagination from '../components/ListPagination.vue'
import ListQueryBar from '../components/ListQueryBar.vue'
import MultimodalPanel from '../components/MultimodalPanel.vue'
import StructuredPanel from '../components/StructuredPanel.vue'
import RbacAdminPanel from '../components/RbacAdminPanel.vue'
import ProfileFeedbackPanel from '../components/ProfileFeedbackPanel.vue'
import SessionHistoryPanel from '../components/SessionHistoryPanel.vue'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'
import { fixDisplayFilename } from '../utils/filename'

interface MenuNode {
  id: number
  name: string
  path?: string
  menu_type: string
  permission?: string
  children?: MenuNode[]
}

const route = useRoute()
const router = useRouter()
const isSidebarOpen = ref(true)
const menus = ref<MenuNode[]>([])
const kbDocs = ref<KnowledgeDoc[]>([])
const kbTotal = ref(0)
const kbQuery = ref<ListQueryState>(defaultListQuery(20))
const kbStatusFilter = ref('')
const kbSliceMethod = ref('auto')
const kbSliceMethods = ref<{ id: string; label: string; description?: string }[]>([])
const kbVlmLimit = ref(30)
const kbList = ref<KnowledgeBaseBrief[]>([])
const selectedKbId = ref<number | null>(null)
const kbCreating = ref(false)
const kbCreateName = ref('')
const kbCreateDesc = ref('')
const adminLogRows = ref<Record<string, unknown>[]>([])
const adminLogTotal = ref(0)
const adminLogPage = ref(1)
const adminLogSize = ref(20)
const logQuery = ref<ListQueryState>(defaultListQuery(20))
const logModuleFilter = ref('')
const profileNickname = ref('')
const profilePhone = ref('')
const profilePhoneCode = ref('')
const profileMsg = ref('')

const activePath = computed(() => route.path)
const expandedMenuIds = ref<Set<number>>(new Set())

const PROFILE_MENU_ID = 20

const primaryMenus = computed(() =>
  menus.value.filter((m) => m.id !== PROFILE_MENU_ID && m.name !== '个人中心'),
)

const profileMenu = computed(() =>
  menus.value.find((m) => m.id === PROFILE_MENU_ID || m.name === '个人中心') ?? null,
)

const syncExpandedMenus = (): void => {
  const next = new Set<number>()
  const walk = (nodes: MenuNode[]) => {
    for (const n of nodes) {
      if (n.children?.some((c) => c.path === activePath.value)) {
        next.add(n.id)
      }
      if (n.children?.length) walk(n.children)
    }
  }
  walk(menus.value)
  expandedMenuIds.value = next
}

const toggleMenuGroup = (id: number): void => {
  const next = new Set(expandedMenuIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedMenuIds.value = next
}

const isChildMenuActive = (node: MenuNode): boolean =>
  !!node.children?.some((c) => c.path === activePath.value)

const pageTitle = computed(() => {
  const map: Record<string, string> = {
    '/chat': '智能客服会话',
    '/knowledge': '知识库管理',
    '/multimodal': '多模态文档处理',
    '/structured': '结构化处理',
    '/sessions': '会话历史',
    '/profile': '基本资料',
    '/profile/feedback': '回答反馈记录',
    '/admin/logs/operation': '操作日志',
    '/admin/logs/error': '异常日志',
    '/admin/logs/api-call': 'API 调用日志',
    '/admin/logs/schedule': '定时任务日志',
    '/admin/eval': 'EVAL 评测',
    '/admin/agent-config': 'Agent 配置',
    '/admin/agent-gateway': 'Agent 网关',
    '/admin/rbac': '用户权限',
    '/admin/feedback': '用户反馈',
    '/admin/users': '用户权限',
  }
  return map[route.path] || 'HaiCi 智能客服'
})

const adminLogKind = computed(() => {
  if (route.path.endsWith('/error')) return 'error'
  if (route.path.endsWith('/api-call')) return 'api-call'
  if (route.path.endsWith('/schedule')) return 'schedule'
  if (route.path.includes('/admin/logs')) return 'operation'
  return ''
})

const hideGlobalHeader = computed(() => route.path === '/chat')

const loadMenus = async (): Promise<void> => {
  const res = await fetch('/api/v1/auth/menus', { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    menus.value = data.items || []
    syncExpandedMenus()
  }
}

const loadKnowledge = async (): Promise<void> => {
  if (!hasPerm('kb:view')) return
  const extras: Record<string, string | undefined> = { status: kbStatusFilter.value || undefined }
  if (selectedKbId.value) extras.kb_id = String(selectedKbId.value)
  const qs = toSearchParams(kbQuery.value, extras)
  const res = await fetch(`/api/v1/knowledge?${qs}`, { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    kbDocs.value = data.items || []
    kbTotal.value = data.total || 0
    if (data.page) kbQuery.value.page = data.page
    if (data.size) kbQuery.value.size = data.size
  }
}

const resetKbQuery = (): void => {
  kbQuery.value = defaultListQuery(20)
  kbStatusFilter.value = ''
  loadKnowledge()
}

const loadKbList = async (): Promise<void> => {
  try {
    const res = await fetch('/api/v1/knowledge-bases/all', { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      kbList.value = data.items || []
      if (!selectedKbId.value && kbList.value.length) {
        const def = kbList.value.find((k) => k.is_default === 1)
        selectedKbId.value = def ? def.id : kbList.value[0].id
      }
    }
  } catch { /* ignore */ }
}

const createKb = async (): Promise<void> => {
  const name = kbCreateName.value.trim()
  if (!name) return
  const res = await fetch('/api/v1/knowledge-bases', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ name, description: kbCreateDesc.value.trim() || undefined }),
  })
  if (res.ok) {
    kbCreating.value = false
    kbCreateName.value = ''
    kbCreateDesc.value = ''
    await loadKbList()
    const data = await res.json()
    if (data.item?.id) selectedKbId.value = data.item.id
  } else {
    const err = await res.json()
    alert(typeof err.detail === 'string' ? err.detail : '创建失败')
  }
}


const loadSliceMethods = async (): Promise<void> => {
  try {
    const [mRes, cRes] = await Promise.all([
      fetch('/api/v1/knowledge/slice-methods', { headers: authHeaders() }),
      fetch('/api/v1/knowledge/config', { headers: authHeaders() }),
    ])
    if (mRes.ok) {
      const data = await mRes.json()
      kbSliceMethods.value = data.methods || []
      if (data.default) kbSliceMethod.value = data.default
    }
    if (cRes.ok) {
      const cfg = await cRes.json()
      kbVlmLimit.value = cfg.max_images_per_doc ?? 30
    }
  } catch {
    kbSliceMethods.value = [
      { id: 'auto', label: '自动' },
      { id: 'semantic', label: '语义切割' },
      { id: 'dynamic_semantic', label: '动态范围语义' },
      { id: 'md_header', label: 'MD 标题结构' },
      { id: 'paragraph', label: '段落切割' },
      { id: 'ai_semantic', label: 'AI 动态语义段' },
    ]
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
  })
}

const loadAdminLogs = async (): Promise<void> => {
  const kind = adminLogKind.value
  if (!kind) return
  logQuery.value.page = adminLogPage.value
  logQuery.value.size = adminLogSize.value
  const extras: Record<string, string | undefined> = {}
  if (logModuleFilter.value) {
    if (kind === 'schedule') extras.job_name = logModuleFilter.value
    else if (kind === 'api-call') extras.api_type = logModuleFilter.value
    else extras.module = logModuleFilter.value
  }
  const qs = toSearchParams(logQuery.value, extras)
  const res = await fetch(`/api/v1/admin/logs/${kind}?${qs}`, { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    adminLogRows.value = data.items || []
    adminLogTotal.value = data.total || 0
    adminLogPage.value = data.page || logQuery.value.page
    adminLogSize.value = data.size || logQuery.value.size
  }
}

const resetLogQuery = (): void => {
  logQuery.value = defaultListQuery(20)
  logModuleFilter.value = ''
  adminLogPage.value = 1
  loadAdminLogs()
}

const loadMe = async (): Promise<void> => {
  const res = await fetch('/api/v1/auth/me', { headers: authHeaders() })
  if (res.ok) {
    const u = await res.json()
    profileNickname.value = u.nickname || ''
    profilePhone.value = u.phone || ''
  }
}

const logout = async (): Promise<void> => {
  const rt = localStorage.getItem('hc_refresh_token')
  if (rt) {
    await fetch('/api/v1/auth/logout', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ refresh_token: rt }),
    })
  }
  clearAuth()
  router.push('/login')
}

const uploadKnowledge = async (event: Event): Promise<void> => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  fd.append('slice_method', kbSliceMethod.value)
  if (selectedKbId.value) fd.append('kb_id', String(selectedKbId.value))
  const res = await fetch('/api/v1/knowledge/upload', {
    method: 'POST',
    headers: { Authorization: `Bearer ${getAccessToken()}` },
    body: fd,
  })
  const data = await res.json().catch(() => ({}))
  input.value = ''
  if (!res.ok) {
    alert(data.detail || data.error_message || `上传失败 (${res.status})`)
    await loadKnowledge()
    return
  }
  if (data.status === 'failed') {
    alert(`入库失败：${data.error_message || '未知错误'}`)
  }
  await loadKnowledge()
}

const deleteKnowledge = async (id: number): Promise<void> => {
  await fetch(`/api/v1/knowledge/${id}`, { method: 'DELETE', headers: authHeaders() })
  await loadKnowledge()
}

const sendProfileCode = async (): Promise<void> => {
  if (!profilePhone.value.trim()) {
    profileMsg.value = '请先输入手机号'
    return
  }
  const res = await fetch('/api/v1/auth/send-code', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ target: profilePhone.value.trim(), code_type: 'sms', purpose: 'bind' }),
  })
  const data = await res.json()
  profileMsg.value = res.ok ? data.message : data.detail || '发送失败'
}

const saveProfile = async (): Promise<void> => {
  const res = await fetch('/api/v1/auth/profile', {
    method: 'PATCH',
    headers: authHeaders(),
    body: JSON.stringify({
      nickname: profileNickname.value,
      phone: profilePhone.value.trim() || undefined,
      phone_code: profilePhoneCode.value.trim() || undefined,
    }),
  })
  const data = await res.json()
  if (res.ok) {
    profileMsg.value = '保存成功'
    if (currentUser.value) {
      currentUser.value.nickname = data.nickname
      currentUser.value.phone = data.phone
      localStorage.setItem('hc_user', JSON.stringify(currentUser.value))
    }
  } else {
    profileMsg.value = typeof data.detail === 'string' ? data.detail : '保存失败'
  }
}

watch(
  () => route.path,
  async (p) => {
    syncExpandedMenus()
    if (p === '/knowledge') {
      await loadSliceMethods()
      await loadKbList()
      await loadKnowledge()
    }
    if (p === '/profile') await loadMe()
    if (p === '/profile/feedback') { /* ProfileFeedbackPanel 自加载 */ }
    if (p.startsWith('/admin/logs/')) {
      adminLogPage.value = 1
      await loadAdminLogs()
    }
  },
  { immediate: true }
)

watch(() => [kbQuery.value.page, kbQuery.value.size], () => {
  if (route.path === '/knowledge') loadKnowledge()
})

watch(() => [adminLogPage.value, adminLogSize.value], () => {
  if (route.path.startsWith('/admin/logs/')) loadAdminLogs()
})

onMounted(async () => {
  loadAuthFromStorage()
  await loadMenus()
})
</script>

<template>
  <div class="shell-root flex h-full w-full bg-[#f1f5f9] rounded-[24px] border border-[#cbd5e1]/80 shadow-[0_8px_30px_rgb(0,0,0,0.06)] overflow-hidden relative">
    <aside
      :class="isSidebarOpen ? 'w-[200px]' : 'w-[72px]'"
      class="shell-sidebar h-full flex flex-col z-40 shrink-0 transition-all duration-300"
    >
      <div class="shell-sidebar-brand h-16 flex items-center px-4" :class="isSidebarOpen ? '' : 'justify-center'">
        <div class="w-8 h-8 bg-gradient-to-br from-[#363e42] to-[#1a1c1d] text-white rounded-[10px] flex items-center justify-center shrink-0">
          <span class="text-xs font-bold text-[#d97706]">HC</span>
        </div>
        <div v-if="isSidebarOpen" class="ml-3 overflow-hidden">
          <h1 class="text-[13px] font-black text-[#363e42] leading-none">HaiCi 智能客服</h1>
          <p v-if="currentUser?.user_no" class="text-[10px] text-[#363e42]/40 mt-1">NO.{{ currentUser.user_no }}</p>
        </div>
      </div>

      <div class="shell-sidebar-middle flex-1 flex flex-col min-h-0 relative">
        <nav class="shell-sidebar-nav py-4 flex-1 overflow-y-auto px-3 flex flex-col gap-1 min-h-0">
          <template v-for="node in primaryMenus" :key="node.id">
            <div v-if="node.menu_type === 'M' && node.children?.length" class="flex flex-col gap-0.5">
              <button
                type="button"
                class="w-full flex items-center justify-between py-2.5 px-3 rounded-xl text-[12px] font-bold transition-all"
                :class="isChildMenuActive(node) ? 'bg-[#363e42]/10 text-[#363e42]' : 'text-[#363e42] hover:bg-[#363e42]/5'"
                @click="isSidebarOpen ? toggleMenuGroup(node.id) : undefined"
              >
                <span v-if="isSidebarOpen">{{ node.name }}</span>
                <span v-else class="w-full text-center text-[10px]">{{ node.name.slice(0, 2) }}</span>
                <i
                  v-if="isSidebarOpen"
                  class="fas text-[10px] text-[#363e42]/40"
                  :class="expandedMenuIds.has(node.id) ? 'fa-chevron-down' : 'fa-chevron-right'"
                ></i>
              </button>
              <div
                v-if="isSidebarOpen && expandedMenuIds.has(node.id)"
                class="ml-2 pl-2 border-l border-[#363e42]/10 flex flex-col gap-0.5"
              >
                <router-link
                  v-for="child in node.children.filter((c) => c.menu_type === 'C' && c.path)"
                  :key="child.id"
                  :to="child.path || '/'"
                  class="w-full flex items-center py-2 px-3 rounded-lg text-[11px] font-bold transition-all"
                  :class="activePath === child.path ? 'bg-[#363e42] text-white' : 'text-[#363e42]/80 hover:bg-[#363e42]/5'"
                >
                  {{ child.name }}
                </router-link>
              </div>
            </div>
            <router-link
              v-else-if="node.menu_type === 'C' && node.path"
              :to="node.path || '/'"
              class="w-full flex items-center py-2.5 px-3 rounded-xl text-[12px] font-bold transition-all"
              :class="activePath === node.path ? 'bg-[#363e42] text-white' : 'text-[#363e42] hover:bg-[#363e42]/5'"
            >
              <span v-if="isSidebarOpen">{{ node.name }}</span>
              <span v-else class="w-full text-center text-[10px]">{{ node.name.slice(0, 2) }}</span>
            </router-link>
          </template>
        </nav>
        <button
          type="button"
          class="shell-sidebar-toggle"
          :title="isSidebarOpen ? '收起侧栏' : '展开侧栏'"
          @click="isSidebarOpen = !isSidebarOpen"
        >
          <i class="fas text-[11px]" :class="isSidebarOpen ? 'fa-chevron-left' : 'fa-chevron-right'"></i>
        </button>
      </div>

      <div class="shell-sidebar-footer p-3 shrink-0">
        <div class="shell-footer-top-row">
          <div v-if="profileMenu" class="shell-profile-menu">
            <div v-if="profileMenu.menu_type === 'M' && profileMenu.children?.length" class="flex flex-col gap-0.5">
              <button
                type="button"
                class="shell-profile-btn w-full flex items-center justify-between py-2 px-2 rounded-xl text-[12px] font-bold transition-all"
                :class="isChildMenuActive(profileMenu) ? 'bg-[#363e42]/10 text-[#363e42]' : 'text-[#363e42] hover:bg-[#363e42]/5'"
                @click="isSidebarOpen ? toggleMenuGroup(profileMenu.id) : router.push('/profile')"
              >
                <span v-if="isSidebarOpen">{{ profileMenu.name }}</span>
                <span v-else class="w-full text-center text-[10px]">个人</span>
                <i
                  v-if="isSidebarOpen"
                  class="fas text-[10px] text-[#363e42]/40"
                  :class="expandedMenuIds.has(profileMenu.id) ? 'fa-chevron-down' : 'fa-chevron-right'"
                ></i>
              </button>
              <div
                v-if="isSidebarOpen && expandedMenuIds.has(profileMenu.id)"
                class="ml-2 pl-2 border-l border-[#363e42]/10 flex flex-col gap-0.5"
              >
                <router-link
                  v-for="child in profileMenu.children.filter((c) => c.menu_type === 'C' && c.path)"
                  :key="child.id"
                  :to="child.path || '/'"
                  class="w-full flex items-center py-2 px-3 rounded-lg text-[11px] font-bold transition-all"
                  :class="activePath === child.path ? 'bg-[#363e42] text-white' : 'text-[#363e42]/80 hover:bg-[#363e42]/5'"
                >
                  {{ child.name }}
                </router-link>
              </div>
            </div>
          </div>
          <button
            type="button"
            class="shell-logout-btn text-[11px] text-red-500 font-bold shrink-0"
            @click="logout"
          >
            <span v-if="isSidebarOpen">退出登录</span>
            <span v-else class="text-[10px]">退</span>
          </button>
        </div>
      </div>
    </aside>

    <main class="shell-main flex-1 flex flex-col h-full relative min-w-0">
      <header v-if="!hideGlobalHeader" class="shell-main-header h-16 flex items-center px-6 shrink-0">
        <span class="text-[14px] font-black text-[#363e42]">{{ pageTitle }}</span>
      </header>

      <ChatPanel v-if="route.path === '/chat'" />

      <MultimodalPanel v-else-if="route.path === '/multimodal'" />
      <StructuredPanel v-else-if="route.path === '/structured'" />

                  <div v-else-if="route.path === '/knowledge'" class="flex-1 p-6 overflow-y-auto">
        <div class="max-w-5xl mx-auto">
          <div class="flex flex-wrap justify-between items-center gap-3 mb-6">
            <h2 class="text-lg font-black">知识库管理</h2>
            <div class="flex flex-wrap items-center gap-3">
              <!-- 知识库选择器 -->
              <label v-if="kbList.length > 0" class="text-[12px] font-bold text-[#363e42]/60 flex items-center gap-2">
                知识库
                <select v-model="selectedKbId" class="border rounded-lg px-2 py-1.5 text-[12px] font-medium min-w-[140px]" @change="kbQuery.page = 1; loadKnowledge()">
                  <option :value="null">全部文档</option>
                  <option v-for="kb in kbList" :key="kb.id" :value="kb.id">{{ kb.name }} ({{ kb.doc_count }}篇)</option>
                </select>
              </label>
              <button
                v-if="!kbCreating"
                type="button"
                class="text-[11px] font-bold text-[#d97706] border border-[#d97706]/30 rounded-lg px-3 py-1.5 hover:bg-[#d97706]/5 transition-colors"
                @click="kbCreating = true"
              >+ 新建知识库</button>
              <template v-if="kbCreating">
                <input v-model="kbCreateName" type="text" class="border rounded-lg px-2 py-1.5 text-[12px] w-[140px] focus:outline-none focus:border-[#d97706]" placeholder="知识库名称" maxlength="128" />
                <input v-model="kbCreateDesc" type="text" class="border rounded-lg px-2 py-1.5 text-[12px] w-[160px] focus:outline-none focus:border-[#d97706]" placeholder="描述（可选）" maxlength="512" />
                <button type="button" class="text-[11px] font-bold bg-[#363e42] text-white rounded-lg px-3 py-1.5 hover:bg-[#4a5256] transition-colors" @click="createKb">确定</button>
                <button type="button" class="text-[11px] text-[#363e42]/50 hover:text-[#363e42]/70" @click="kbCreating = false">取消</button>
              </template>
              <label class="text-[12px] font-bold text-[#363e42]/60 flex items-center gap-2">
                分块策略
                <select v-model="kbSliceMethod" class="border rounded-lg px-2 py-1.5 text-[12px] font-medium min-w-[160px]">
                  <option v-for="m in kbSliceMethods" :key="m.id" :value="m.id">{{ m.label }}</option>
                </select>
              </label>
              <label v-if="hasPerm('kb:upload')" class="bg-[#363e42] text-white px-5 py-2.5 rounded-xl font-bold text-[13px] cursor-pointer hover:bg-[#4a5256] transition-colors shadow-sm">
                上传文档
                <input type="file" class="hidden" accept=".txt,.md,.pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg" @change="uploadKnowledge" />
              </label>
            </div>
          </div>

          <!-- 知识库卡片 -->
          <div v-if="kbList.length > 0" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
            <div
              v-for="kb in kbList"
              :key="kb.id"
              :class="[
                'relative rounded-2xl border-2 p-5 cursor-pointer transition-all duration-200 hover:shadow-lg',
                selectedKbId === kb.id
                  ? 'border-[#d97706] bg-[#d97706]/5 shadow-md'
                  : 'border-[#e5e7eb] bg-white hover:border-[#d97706]/40'
              ]"
              @click="selectedKbId = kb.id; kbQuery.page = 1; loadKnowledge()"
            >
              <div class="flex items-start justify-between mb-3">
                <div class="flex items-center gap-2.5">
                  <div :class="[
                    'w-9 h-9 rounded-xl flex items-center justify-center text-sm font-black',
                    selectedKbId === kb.id ? 'bg-[#d97706] text-white' : 'bg-[#f3f4f6] text-[#363e42]'
                  ]">
                    {{ kb.name.charAt(0).toUpperCase() }}
                  </div>
                  <div>
                    <div class="text-sm font-bold text-[#363e42] leading-tight">{{ kb.name }}</div>
                    <div v-if="kb.description" class="text-[11px] text-[#64748b] mt-0.5 line-clamp-2">{{ kb.description }}</div>
                  </div>
                </div>
                <span v-if="kb.is_default === 1" class="text-[10px] font-bold bg-[#fef3c7] text-[#d97706] px-2 py-0.5 rounded-full">默认</span>
              </div>
              <div class="flex items-center gap-4 text-[11px] text-[#64748b]">
                <span class="flex items-center gap-1">
                  <span class="text-[#d97706]">文档</span> {{ kb.doc_count }} 篇
                </span>
                <span class="flex items-center gap-1">
                  <span class="text-[#d97706]">创建</span> {{ fmtDateTime(kb.created_at) }}
                </span>
              </div>
              <div v-if="selectedKbId === kb.id" class="absolute top-3 right-3 w-5 h-5 bg-[#d97706] rounded-full flex items-center justify-center">
                <span class="text-white text-[10px] font-black">✓</span>
              </div>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="kbList.length === 0 && !kbCreating" class="text-center py-16 mb-6 bg-white rounded-2xl border-2 border-dashed border-[#e5e7eb]">
            <div class="text-5xl mb-4">📚</div>
            <h3 class="text-base font-bold text-[#363e42] mb-2">还没有知识库</h3>
            <p class="text-sm text-[#64748b] mb-5 max-w-md mx-auto leading-relaxed">
              创建知识库后，可上传 PDF、Word、Excel 等文档，系统会自动 OCR/VLM 识别并写入向量库，供 AI 问答检索。
            </p>
            <button
              type="button"
              class="inline-flex items-center gap-2 bg-[#d97706] text-white px-5 py-2.5 rounded-xl font-bold text-sm hover:bg-[#c26806] transition-colors shadow-sm"
              @click="kbCreating = true"
            >
              <span class="text-lg">+</span> 创建第一个知识库
            </button>
          </div>

          <p class="text-[11px] text-[#363e42]/50 mb-4">
            含图文档（PDF/DOCX/XLS 等）会先标准化：抽图 → OCR/VLM 识别 → 写入 kb_assets；单文档 VLM 上限
            <strong>{{ kbVlmLimit }}</strong> 张。图片经 <code>/output/kb_assets/...</code> 可在回答界面渲染。
          </p>
          <ListQueryBar
            v-model="kbQuery"
            :sort-options="[
              { value: 'created_at', label: '上传时间' },
              { value: 'filename', label: '文档名' },
              { value: 'status', label: '状态' },
              { value: 'chunk_count', label: '分块数' },
            ]"
            name-placeholder="文档文件名"
            keyword-placeholder="文件名关键词"
            @search="loadKnowledge"
            @reset="resetKbQuery"
          />
          <div class="flex items-center gap-3 mb-3 text-[11px] font-bold text-[#363e42]/60">
            <label>状态筛选
              <select v-model="kbStatusFilter" class="ml-2 border rounded px-2 py-1" @change="kbQuery.page = 1; loadKnowledge()">
                <option value="">全部</option>
                <option value="ready">ready</option>
                <option value="processing">processing</option>
                <option value="failed">failed</option>
              </select>
            </label>
          </div>
          <table class="w-full bg-white rounded-2xl border text-sm overflow-hidden">
            <thead class="bg-[#fcfcfc] text-[#363e42]/60">
              <tr>
                <th class="p-3 text-left">文档</th>
                <th class="p-3 text-left">知识库</th>
                <th class="p-3 text-left">类型</th>
                <th class="p-3 text-left">大小</th>
                <th class="p-3 text-left">图片</th>
                <th class="p-3 text-left">状态</th>
                <th class="p-3 text-left">分块</th>
                <th class="p-3 text-left">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in kbDocs" :key="d.id" class="border-t">
                <td class="p-3">{{ fixDisplayFilename(d.filename) }}</td>
                <td class="p-3 text-[11px] text-[#64748b]">{{ d.kb_name || '未分类' }}</td>
                <td class="p-3 uppercase text-[11px]">{{ d.file_type || '-' }}</td>
                <td class="p-3 text-[11px]">{{ d.file_size_human || (d.file_size_bytes ? `${d.file_size_bytes} B` : '-') }}</td>
                <td class="p-3 text-[11px]">
                  {{ d.image_count ?? 0 }}
                  <span v-if="d.truncated" class="text-[#d97706]">（超上限）</span>
                </td>
                <td class="p-3">{{ d.status }}</td>
                <td class="p-3">{{ d.chunk_count }}</td>
                <td class="p-3"><button v-if="hasPerm('kb:delete')" class="text-red-500" @click="deleteKnowledge(d.id)">删除</button></td>
              </tr>
            </tbody>
          </table>
          <ListPagination v-model:page="kbQuery.page" v-model:size="kbQuery.size" :total="kbTotal" />
        </div>
      </div>

      <SessionHistoryPanel v-else-if="route.path === '/sessions'" class="flex-1 p-6 overflow-hidden flex flex-col min-h-0" />

      <EvalDashboard v-else-if="route.path === '/admin/eval'" class="flex-1 p-6 overflow-y-auto" />
      <FeedbackAdminPanel v-else-if="route.path === '/admin/feedback'" class="flex-1 p-6 overflow-y-auto" />
      <AdminUsersPanel v-else-if="route.path === '/admin/users'" class="flex-1 p-6 overflow-y-auto" />
      <AgentConfigPanel v-else-if="route.path === '/admin/agent-config'" class="flex-1 overflow-y-auto" />
      <GatewayPanel v-else-if="route.path === '/admin/agent-gateway'" class="flex-1 overflow-y-auto" />
      <GatewaySecurityPanel v-else-if="route.path === '/admin/gateway-security'" class="flex-1 overflow-y-auto" />
      <GatewayCachePanel v-else-if="route.path === '/admin/gateway-cache'" class="flex-1 overflow-y-auto" />
      <GatewayCircuitPanel v-else-if="route.path === '/admin/gateway-circuit'" class="flex-1 overflow-y-auto" />
      <RbacAdminPanel v-else-if="route.path === '/admin/rbac'" class="flex-1 overflow-y-auto" />

      <div v-else-if="route.path.startsWith('/admin/logs/')" class="flex-1 p-6 overflow-y-auto">
        <div class="max-w-6xl mx-auto bg-white rounded-2xl border overflow-hidden">
          <div class="p-4 border-b">
            <span class="text-sm font-bold text-[#363e42]/60">运维日志（只读）</span>
          </div>
          <ListQueryBar
            v-model="logQuery"
            :sort-options="[{ value: 'created_at', label: '创建时间' }, { value: 'log_id', label: '日志 ID' }]"
            :name-placeholder="adminLogKind === 'schedule' ? '任务名' : adminLogKind === 'api-call' ? 'API 类型' : '模块名'"
            keyword-placeholder="URL/trace/错误信息关键词"
            @search="adminLogPage = 1; loadAdminLogs()"
            @reset="resetLogQuery"
          />
          <div class="px-3 pb-2 text-[11px] font-bold text-[#363e42]/60">
            <label>{{ adminLogKind === 'schedule' ? '任务名' : adminLogKind === 'api-call' ? 'API 类型' : '模块' }}
              <input v-model="logModuleFilter" class="ml-2 border rounded px-2 py-1 font-normal" placeholder="精确筛选" @keyup.enter="adminLogPage = 1; loadAdminLogs()" />
            </label>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead class="bg-[#fcfcfc] text-[#363e42]/60">
                <tr>
                  <th v-for="col in Object.keys(adminLogRows[0] || { log_id: 1, created_at: 1 }).slice(0, 8)" :key="col" class="p-2 text-left whitespace-nowrap">{{ col }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in adminLogRows" :key="idx" class="border-t">
                  <td v-for="col in Object.keys(adminLogRows[0] || { log_id: 1, created_at: 1 }).slice(0, 8)" :key="col" class="p-2 max-w-[200px] truncate">{{ row[col] }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="!adminLogRows.length" class="p-8 text-center text-[#363e42]/40">暂无日志</p>
          <ListPagination v-model:page="adminLogPage" v-model:size="adminLogSize" :total="adminLogTotal" />
        </div>
      </div>

      <ProfileFeedbackPanel v-else-if="route.path === '/profile/feedback'" class="flex-1 p-6 overflow-y-auto" />

      <div v-else-if="route.path === '/profile'" class="flex-1 p-6 overflow-y-auto">
        <div class="max-w-md mx-auto bg-white rounded-2xl border p-6 space-y-3">
          <div class="text-sm"><span class="text-[#363e42]/50">用户号：</span>{{ currentUser?.user_no }}</div>
          <div class="text-sm"><span class="text-[#363e42]/50">邮箱：</span>{{ currentUser?.email || '未绑定' }}</div>
          <input v-model="profileNickname" class="w-full border rounded-lg p-2 text-sm" placeholder="昵称" />
          <input v-model="profilePhone" class="w-full border rounded-lg p-2 text-sm" placeholder="绑定手机号" />
          <div class="flex gap-2">
            <input v-model="profilePhoneCode" class="flex-1 border rounded-lg p-2 text-sm" placeholder="短信验证码" />
            <button class="px-3 rounded-lg bg-[#363e42]/10 text-xs font-bold" @click="sendProfileCode">获取验证码</button>
          </div>
          <button class="w-full bg-[#363e42] text-white py-2 rounded-lg font-bold" @click="saveProfile">保存</button>
          <p v-if="profileMsg" class="text-xs text-center text-[#d97706]">{{ profileMsg }}</p>
        </div>
      </div>
    </main>
  </div>
</template>
