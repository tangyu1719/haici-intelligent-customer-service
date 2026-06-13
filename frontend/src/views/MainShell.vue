<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authHeaders, clearAuth, currentUser, getAccessToken, hasPerm, loadAuthFromStorage } from '../api/auth'
import type { ChatSessionItem, KnowledgeBaseBrief, KnowledgeDoc, LlmGatewaySnapshot } from '../types'
import AgentConfigPanel from '../components/AgentConfigPanel.vue'
import GatewayPanel from '../components/GatewayPanel.vue'
import GatewaySecurityPanel from '../components/GatewaySecurityPanel.vue'
import GatewayCachePanel from '../components/GatewayCachePanel.vue'
import GatewayCircuitPanel from '../components/GatewayCircuitPanel.vue'
import ChatPanel from '../components/ChatPanel.vue'
import EvalDashboard from '../components/EvalDashboard.vue'
import FeedbackAdminPanel from '../components/FeedbackAdminPanel.vue'
import ListPagination from '../components/ListPagination.vue'
import ListQueryBar from '../components/ListQueryBar.vue'
import MultimodalPanel from '../components/MultimodalPanel.vue'
import StructuredPanel from '../components/StructuredPanel.vue'
import ProfileFeedbackPanel from '../components/ProfileFeedbackPanel.vue'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'

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
const sessionList = ref<ChatSessionItem[]>([])
const sessionTotal = ref(0)
const sessionQuery = ref<ListQueryState>(defaultListQuery(20))
const msgQuery = ref<ListQueryState>({ ...defaultListQuery(30), sortBy: 'created_at', sortOrder: 'asc' })
const sessionMessages = ref<{ id: number; role: string; content: string; intent_label?: string; created_at: string }[]>([])
const msgTotal = ref(0)
const selectedSessionId = ref<number | null>(null)
const sessionDetail = ref<{
  id: number
  context_id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
  messages: { id: number; role: string; content: string; intent_label?: string; created_at: string }[]
} | null>(null)
const editingSessionId = ref<number | null>(null)
const editingSessionTitle = ref('')
const editingSessionNote = ref('')
const adminLogRows = ref<Record<string, unknown>[]>([])
const adminLogTotal = ref(0)
const adminLogPage = ref(1)
const adminLogSize = ref(20)
const logQuery = ref<ListQueryState>(defaultListQuery(20))
const logModuleFilter = ref('')
const llmGateway = ref<LlmGatewaySnapshot | null>(null)
const profileNickname = ref('')
const profilePhone = ref('')
const profilePhoneCode = ref('')
const profileMsg = ref('')

const activePath = computed(() => route.path)
const expandedMenuIds = ref<Set<number>>(new Set())

const syncExpandedMenus = (): void => {
  const next = new Set<number>()
  const walk = (nodes: MenuNode[]) => {
    for (const n of nodes) {
      // 自动展开包含当前路由的父菜单
      if (n.children?.some((c) => c.path === activePath.value || c.children?.some((gc: MenuNode) => gc.path === activePath.value))) {
        next.add(n.id)
      }
      // 默认展开所有含子菜单的目录（知识库 / Agent设置 等），避免二级菜单被折叠隐藏
      if (n.menu_type === 'M' && (n.children?.length ?? 0) > 0) {
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
    '/admin/gateway-security': '安全合规',
    '/admin/gateway-cache': '缓存管理',
    '/admin/gateway-circuit': '熔断监控',
    '/admin/feedback': '用户反馈',
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

const visibleMenus = computed(() => menus.value)
const hideGlobalHeader = computed(() => route.path === '/chat')

const loadMenus = async (): Promise<void> => {
  const res = await fetch('/api/v1/auth/menus', { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    menus.value = data.items || []
    setTimeout(() => syncExpandedMenus(), 100)
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

const loadSessions = async (): Promise<void> => {
  if (!hasPerm('session:view')) return
  const qs = toSearchParams(sessionQuery.value)
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
  loadSessions()
}

const loadSessionMessages = async (sessionId: number): Promise<void> => {
  const qs = toSearchParams(msgQuery.value)
  const res = await fetch(`/api/v1/sessions/${sessionId}/messages?${qs}`, { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    sessionMessages.value = data.items || []
    msgTotal.value = data.total || 0
    if (data.page) msgQuery.value.page = data.page
    if (data.size) msgQuery.value.size = data.size
  }
}

const openSessionDetail = async (id: number): Promise<void> => {
  selectedSessionId.value = id
  editingSessionId.value = null
  msgQuery.value.page = 1
  const res = await fetch(`/api/v1/sessions/${id}`, { headers: authHeaders() })
  if (res.ok) {
    sessionDetail.value = await res.json()
    await loadSessionMessages(id)
  }
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
  if (!window.confirm('确定归档该会话？')) return
  await fetch(`/api/v1/sessions/${id}`, { method: 'DELETE', headers: authHeaders() })
  if (selectedSessionId.value === id) {
    selectedSessionId.value = null
    sessionDetail.value = null
  }
  await loadSessions()
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

const loadLlmGateway = async (): Promise<void> => {
  try {
    const res = await fetch('/api/v1/system/llm-gateway', { headers: authHeaders() })
    if (res.ok) llmGateway.value = await res.json()
  } catch {
    llmGateway.value = null
  }
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

const providerLabel = (p: string): string => {
  const map: Record<string, string> = { ark: '火山方舟 ARK', qwen: '通义千问', openai_compatible: 'OpenAI 兼容' }
  return map[p] || p || '未配置'
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
    if (p === '/sessions') {
      selectedSessionId.value = null
      sessionDetail.value = null
      sessionMessages.value = []
      await loadSessions()
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

watch(() => [sessionQuery.value.page, sessionQuery.value.size], () => {
  if (route.path === '/sessions') loadSessions()
})

watch(() => [msgQuery.value.page, msgQuery.value.size], () => {
  if (selectedSessionId.value) loadSessionMessages(selectedSessionId.value)
})

watch(() => [adminLogPage.value, adminLogSize.value], () => {
  if (route.path.startsWith('/admin/logs/')) loadAdminLogs()
})

onMounted(async () => {
  loadAuthFromStorage()
  await loadMenus()
  await loadLlmGateway()
})
</script>

<template>
  <div class="flex h-full w-full bg-white rounded-[24px] border border-[#363e42]/5 shadow-[0_8px_30px_rgb(0,0,0,0.04)] overflow-hidden relative">
    <aside
      :class="isSidebarOpen ? 'w-[200px]' : 'w-[72px]'"
      class="h-full bg-white border-r border-[#363e42]/5 flex flex-col z-40 shrink-0 transition-all duration-300"
    >
      <div class="h-16 flex items-center border-b border-[#363e42]/5 px-4" :class="isSidebarOpen ? '' : 'justify-center'">
        <div class="w-8 h-8 bg-gradient-to-br from-[#363e42] to-[#1a1c1d] text-white rounded-[10px] flex items-center justify-center shrink-0">
          <span class="text-xs font-bold text-[#d97706]">HC</span>
        </div>
        <div v-if="isSidebarOpen" class="ml-3 overflow-hidden">
          <h1 class="text-[13px] font-black text-[#363e42] leading-none">HaiCi 智能客服</h1>
          <p v-if="currentUser?.user_no" class="text-[10px] text-[#363e42]/40 mt-1">NO.{{ currentUser.user_no }}</p>
        </div>
      </div>

      <nav class="py-4 flex-1 bg-[#fcfcfc] overflow-y-auto px-3 flex flex-col gap-1">
        <template v-for="node in visibleMenus" :key="node.id">
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
              <template v-for="child in node.children" :key="child.id">
                <!-- 子目录（三级菜单父节点） -->
                <div v-if="child.menu_type === 'M' && child.children?.length" class="flex flex-col gap-0.5">
                  <button
                    class="w-full flex items-center justify-between py-1.5 px-2 rounded-lg text-[11px] font-bold transition-all hover:bg-[#363e42]/5"
                    :class="isChildMenuActive(child) ? 'text-[#d97706]' : 'text-[#64748b]'"
                    @click="toggleMenuGroup(child.id)"
                  >
                    <span>{{ child.name }}</span>
                    <i class="fas text-[9px]" :class="expandedMenuIds.has(child.id) ? 'fa-chevron-down' : 'fa-chevron-right'"></i>
                  </button>
                  <div v-if="expandedMenuIds.has(child.id)" class="ml-2 pl-2 border-l border-[#363e42]/8 flex flex-col gap-0.5">
                    <router-link
                      v-for="gc in child.children.filter((c:MenuNode) => c.menu_type === 'C' && c.path)"
                      :key="gc.id" :to="gc.path || '/'"
                      class="w-full flex items-center py-1.5 px-2 rounded-lg text-[10px] font-bold transition-all"
                      :class="activePath === gc.path ? 'bg-[#363e42] text-white' : 'text-[#64748b] hover:bg-[#363e42]/5'"
                    >{{ gc.name }}</router-link>
                  </div>
                </div>
                <!-- 叶子节点 -->
                <router-link
                  v-else-if="child.menu_type === 'C' && child.path"
                  :to="child.path || '/'"
                  class="w-full flex items-center py-1.5 px-2 rounded-lg text-[11px] font-bold transition-all"
                  :class="activePath === child.path ? 'bg-[#363e42] text-white' : 'text-[#363e42]/80 hover:bg-[#363e42]/5'"
                >{{ child.name }}</router-link>
              </template>
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

      <div class="p-3 border-t border-[#363e42]/5 flex flex-col gap-2">
        <button class="text-[11px] text-red-500 font-bold" @click="logout">退出登录</button>
        <button class="w-8 h-8 mx-auto flex items-center justify-center rounded-lg text-[#363e42]/40 hover:bg-[#363e42]/10" @click="isSidebarOpen = !isSidebarOpen">
          <i class="fas text-[12px]" :class="isSidebarOpen ? 'fa-chevron-left' : 'fa-chevron-right'"></i>
        </button>
      </div>
    </aside>

    <main class="flex-1 flex flex-col h-full bg-[#fdf6e3]/30 relative">
      <header v-if="!hideGlobalHeader" class="h-16 border-b border-[#363e42]/5 bg-white/80 backdrop-blur-md flex items-center justify-between px-6 shrink-0">
        <span class="text-[14px] font-black text-[#363e42]">{{ pageTitle }}</span>
        <div v-if="llmGateway?.active_chat?.name" class="text-right hidden sm:block">
          <div class="text-[11px] font-bold text-[#363e42]">{{ providerLabel(llmGateway.active_chat.provider) }} · {{ llmGateway.active_chat.name }}</div>
          <div class="text-[10px] text-[#363e42]/50 font-mono">{{ llmGateway.active_chat.model }}</div>
        </div>
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
                class="text-[11px] font-bold text-[#d97706] border border-[#d97706]/30 rounded-lg px-3 py-1.5"
                @click="kbCreating = true"
              >+ 新建知识库</button>
              <template v-if="kbCreating">
                <input v-model="kbCreateName" type="text" class="border rounded-lg px-2 py-1.5 text-[12px] w-[140px]" placeholder="知识库名称" maxlength="128" />
                <input v-model="kbCreateDesc" type="text" class="border rounded-lg px-2 py-1.5 text-[12px] w-[160px]" placeholder="描述（可选）" maxlength="512" />
                <button type="button" class="text-[11px] font-bold bg-[#363e42] text-white rounded-lg px-3 py-1.5" @click="createKb">确定</button>
                <button type="button" class="text-[11px] text-[#363e42]/50" @click="kbCreating = false">取消</button>
              </template>
              <label class="text-[12px] font-bold text-[#363e42]/60 flex items-center gap-2">
                分块策略
                <select v-model="kbSliceMethod" class="border rounded-lg px-2 py-1.5 text-[12px] font-medium min-w-[160px]">
                  <option v-for="m in kbSliceMethods" :key="m.id" :value="m.id">{{ m.label }}</option>
                </select>
              </label>
              <label v-if="hasPerm('kb:upload')" class="bg-[#363e42] text-white px-5 py-2.5 rounded-xl font-bold text-[13px] cursor-pointer">
                上传文档
                <input type="file" class="hidden" accept=".txt,.md,.pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg" @change="uploadKnowledge" />
              </label>
            </div>
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
                <td class="p-3">{{ d.filename }}</td>
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

      <div v-else-if="route.path === '/sessions'" class="flex-1 p-6 overflow-y-auto">
        <div class="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-5 gap-4">
          <div class="lg:col-span-3 bg-white rounded-2xl border overflow-hidden">
            <ListQueryBar
              v-model="sessionQuery"
              :sort-options="[
                { value: 'updated_at', label: '最后更新' },
                { value: 'created_at', label: '创建时间' },
                { value: 'title', label: '会话名称' },
                { value: 'id', label: '会话 ID' },
              ]"
              name-placeholder="会话标题"
              keyword-placeholder="标题/会话名称"
              @search="loadSessions"
              @reset="resetSessionQuery"
            />
            <table class="w-full text-sm">
              <thead class="bg-[#fcfcfc] text-[#363e42]/60 text-[11px]">
                <tr>
                  <th class="p-3 text-left">ID</th>
                  <th class="p-3 text-left">追踪 ID</th>
                  <th class="p-3 text-left">名称</th>
                  <th class="p-3 text-left">创建时间</th>
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
                  <td class="p-3 font-mono text-[10px] text-[#363e42]/60 max-w-[120px] truncate" :title="s.context_id">{{ s.context_id }}</td>
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
                  <td class="p-3 text-[11px] whitespace-nowrap">{{ fmtDateTime(s.created_at) }}</td>
                  <td class="p-3 text-[11px] whitespace-nowrap">{{ fmtDateTime(s.updated_at) }}</td>
                  <td class="p-3 text-[11px]">{{ s.message_count ?? s.meta?.message_count ?? 0 }}</td>
                  <td class="p-3 whitespace-nowrap" @click.stop>
                    <template v-if="editingSessionId === s.id">
                      <button class="text-[11px] text-[#d97706] font-bold mr-2" @click="saveEditSessionRow(s.id)">保存</button>
                      <button class="text-[11px] text-[#363e42]/50" @click="cancelEditSessionRow">取消</button>
                    </template>
                    <template v-else>
                      <button class="text-[11px] text-[#363e42] font-bold mr-2" @click="startEditSessionRow(s, $event)">编辑</button>
                      <button class="text-[11px] text-red-500" @click="archiveSessionRow(s.id, $event)">归档</button>
                    </template>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-if="!sessionList.length" class="p-8 text-center text-[#363e42]/40 text-sm">暂无历史会话</p>
            <ListPagination v-model:page="sessionQuery.page" v-model:size="sessionQuery.size" :total="sessionTotal" />
          </div>
          <div class="lg:col-span-2 bg-white rounded-2xl border p-4 min-h-[320px] flex flex-col">
            <template v-if="sessionDetail">
              <h3 class="font-black text-sm mb-1">{{ sessionDetail.title }}</h3>
              <div class="text-[10px] text-[#363e42]/50 space-y-0.5 mb-3">
                <div>会话 ID：{{ sessionDetail.id }}</div>
                <details class="text-[10px]">
                  <summary class="cursor-pointer text-[#363e42]/45 select-none">追踪 ID（运维/反馈用）</summary>
                  <div class="font-mono break-all mt-1 text-[#363e42]/60">{{ sessionDetail.context_id }}</div>
                </details>
                <div>创建：{{ fmtDateTime(sessionDetail.created_at) }}</div>
                <div>更新：{{ fmtDateTime(sessionDetail.updated_at) }}</div>
                <div>消息数：{{ sessionDetail.message_count }}</div>
              </div>
              <ListQueryBar
                v-model="msgQuery"
                :show-name="false"
                :sort-options="[{ value: 'created_at', label: '消息时间' }, { value: 'id', label: '消息 ID' }]"
                keyword-placeholder="消息内容关键词"
                @search="selectedSessionId && loadSessionMessages(selectedSessionId)"
                @reset="msgQuery = { ...defaultListQuery(30), sortBy: 'created_at', sortOrder: 'asc' }; selectedSessionId && loadSessionMessages(selectedSessionId)"
              />
              <div class="space-y-3 flex-1 overflow-y-auto mt-3 min-h-0">
                <div
                  v-for="m in sessionMessages"
                  :key="m.id"
                  class="p-3 rounded-xl text-[13px] border"
                  :class="m.role === 'user' ? 'bg-[#d97706]/10 border-[#d97706]/20' : 'bg-[#fcfcfc]'"
                >
                  <div class="text-[10px] font-bold text-[#363e42]/40 mb-1">{{ m.role === 'user' ? '用户' : '助手' }} · #{{ m.id }} · {{ fmtDateTime(m.created_at) }}</div>
                  <div class="whitespace-pre-wrap">{{ m.content }}</div>
                  <div v-if="m.intent_label" class="text-[10px] text-[#d97706] mt-1">意图: {{ m.intent_label }}</div>
                </div>
              </div>
              <ListPagination v-model:page="msgQuery.page" v-model:size="msgQuery.size" :total="msgTotal" />
            </template>
            <p v-else class="text-center text-[#363e42]/40 text-sm pt-16">点击左侧会话查看消息回放</p>
          </div>
        </div>
      </div>

      <EvalDashboard v-else-if="route.path === '/admin/eval'" class="flex-1 p-6 overflow-y-auto" />
      <FeedbackAdminPanel v-else-if="route.path === '/admin/feedback'" class="flex-1 p-6 overflow-y-auto" />
      <AgentConfigPanel v-else-if="route.path === '/admin/agent-config'" class="flex-1 overflow-y-auto" />
      <GatewayPanel v-else-if="route.path === '/admin/agent-gateway'" class="flex-1 overflow-y-auto" />
      <GatewaySecurityPanel v-else-if="route.path === '/admin/gateway-security'" class="flex-1 overflow-y-auto" />
      <GatewayCachePanel v-else-if="route.path === '/admin/gateway-cache'" class="flex-1 overflow-y-auto" />
      <GatewayCircuitPanel v-else-if="route.path === '/admin/gateway-circuit'" class="flex-1 overflow-y-auto" />

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
