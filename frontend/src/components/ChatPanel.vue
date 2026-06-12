<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { authHeaders, getAccessToken } from '../api/auth'
import ChatAssistantMessage from './ChatAssistantMessage.vue'
import ListPagination from './ListPagination.vue'
import { hydrateMsgCitations } from '../utils/ragCitations'
import { INTENT_LABELS } from '../utils/intentLabels'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'
import type { ChatAttachment, ChatMessage, ChatPendingUpload, ChatSessionItem, KnowledgeBaseBrief, PlatformHealthSnapshot } from '../types'

const bearerOnly = (): Record<string, string> => {
  const t = getAccessToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

const MAX_PENDING_UPLOADS = 6

const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const isWaiting = ref(false)
const sessionId = ref<number | null>(null)
const chatSessions = ref<ChatSessionItem[]>([])
const sessionTotal = ref(0)
const sessionQuery = ref<ListQueryState>({ ...defaultListQuery(15), sortBy: 'updated_at', sortOrder: 'desc' })
const sessionSearchOpen = ref(false)
const health = ref<PlatformHealthSnapshot | null>(null)
const healthLoading = ref(false)
const healthOpen = ref(false)
const sessionSidebarOpen = ref(true)
const editingSessionId = ref<number | null>(null)
const editingTitle = ref('')
const maxQuestionLength = ref(500)
const kbList = ref<KnowledgeBaseBrief[]>([])
const selectedKbId = ref<number | null>(null)
const pendingUploads = ref<ChatPendingUpload[]>([])
const imageInputRef = ref<HTMLInputElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const inputCharCount = computed(() => inputText.value.length)
const canSend = computed(() => {
  if (isWaiting.value) return false
  const hasText = inputText.value.trim().length > 0
  const hasReadyUpload = pendingUploads.value.some((u) => u.path && !u.uploading && !u.error)
  const uploading = pendingUploads.value.some((u) => u.uploading)
  return (hasText || hasReadyUpload) && !uploading
})

const fmtDateShort = (s?: string): string => {
  if (!s) return '-'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const contextTitle = computed(() => {
  const cur = chatSessions.value.find((s) => s.id === sessionId.value)
  const t = (cur?.title || '').trim()
  return t && t !== '新对话' ? t : sessionId.value ? `会话 #${sessionId.value}` : '新对话'
})

const currentContextId = computed(() => {
  const cur = chatSessions.value.find((s) => s.id === sessionId.value)
  return cur?.context_id || ''
})

const buildContextSummary = (uptoIndex: number): string => {
  return messages.value
    .slice(Math.max(0, uptoIndex - 5), uptoIndex + 1)
    .map((m) => `${m.role === 'user' ? '用户' : '助手'}: ${(m.content || '').slice(0, 120)}`)
    .join('\n')
}

const healthSummary = computed(() => {
  if (healthLoading.value) return '检测中…'
  if (!health.value?.ready) return '未检测'
  const s = health.value.summary
  return `${s.ok} 正常 · ${s.error} 异常`
})

const loadPlatformHealth = async (refresh = false): Promise<void> => {
  if (healthLoading.value) return
  healthLoading.value = true
  try {
    const q = refresh ? '?refresh=1' : ''
    const res = await fetch(`/api/v1/system/platform/health${q}`, { headers: authHeaders() })
    const data = await res.json()
    if (res.ok) health.value = data
    else health.value = { ready: false, all_ok: false, summary: { ok: 0, warn: 0, error: 1 }, items: [], error: data.detail || '健康检查失败' }
  } catch (e) {
    health.value = {
      ready: false,
      all_ok: false,
      summary: { ok: 0, warn: 0, error: 1 },
      items: [],
      error: (e as Error).message || '健康检查请求失败',
    }
  } finally {
    healthLoading.value = false
  }
}

const loadChatConfig = async (): Promise<void> => {
  try {
    const res = await fetch('/api/v1/chat/config', { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      maxQuestionLength.value = data.max_question_length ?? 500
    }
  } catch {
    maxQuestionLength.value = 500
  }
}

const loadKbList = async (): Promise<void> => {
  try {
    const res = await fetch('/api/v1/knowledge-bases/all', { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      kbList.value = data.items || []
      if (!selectedKbId.value && kbList.value.length) {
        const def = kbList.value.find((k: KnowledgeBaseBrief) => k.is_default === 1)
        selectedKbId.value = def ? def.id : null
      }
    }
  } catch { /* ignore */ }
}
const loadChatSessions = async (): Promise<void> => {
  const qs = toSearchParams(sessionQuery.value)
  const res = await fetch(`/api/v1/sessions?${qs}`, { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    chatSessions.value = data.items || []
    sessionTotal.value = data.total || 0
    if (data.page) sessionQuery.value.page = data.page
    if (data.size) sessionQuery.value.size = data.size
  }
}

const resetSessionSidebarQuery = (): void => {
  sessionQuery.value = { ...defaultListQuery(15), sortBy: 'updated_at', sortOrder: 'desc' }
  loadChatSessions()
}

const ensureSession = async (): Promise<number> => {
  if (sessionId.value) return sessionId.value
  const res = await fetch('/api/v1/sessions', { method: 'POST', headers: authHeaders() })
  const data = await res.json()
  sessionId.value = data.id as number
  await loadChatSessions()
  return sessionId.value as number
}

const loadSessionMessages = async (id: number): Promise<void> => {
  const qs = toSearchParams({ ...defaultListQuery(500), sortBy: 'created_at', sortOrder: 'asc', page: 1, keyword: '', dateFrom: '', dateTo: '', id: '', name: '' })
  const res = await fetch(`/api/v1/sessions/${id}/messages?${qs}`, { headers: authHeaders() })
  if (!res.ok) {
    const fallback = await fetch(`/api/v1/sessions/${id}`, { headers: authHeaders() })
    if (!fallback.ok) return
    const data = await fallback.json()
    messages.value = mapHistoryMessages(data.messages || [])
    return
  }
  const data = await res.json()
  messages.value = mapHistoryMessages(data.items || [])
  scrollToBottom()
}

const mapHistoryMessages = (rows: { role: string; content: string; intent_label?: string; citations?: unknown; id: number }[]): ChatMessage[] =>
  rows.map((m) => {
    const code = m.intent_label || ''
    const msg: ChatMessage = {
      role: m.role as 'user' | 'assistant',
      content: m.content,
      intent: code,
      intentLabel: INTENT_LABELS[code] || code,
      citations: Array.isArray(m.citations) ? m.citations : [],
      ragPrefetchSlices: Array.isArray(m.citations) ? m.citations : [],
      messageId: m.id,
      isStreaming: false,
    }
    if (msg.role === 'assistant') hydrateMsgCitations(msg)
    return msg
  })

const switchSession = async (id: number): Promise<void> => {
  if (isWaiting.value) return
  sessionId.value = id
  await loadSessionMessages(id)
}

const newSession = async (): Promise<void> => {
  if (isWaiting.value) return
  const res = await fetch('/api/v1/sessions', { method: 'POST', headers: authHeaders() })
  if (!res.ok) return
  const data = await res.json()
  sessionId.value = data.id
  messages.value = []
  editingSessionId.value = null
  await loadChatSessions()
}

const startEditSession = (s: ChatSessionItem, e: Event): void => {
  e.stopPropagation()
  if (isWaiting.value) return
  editingSessionId.value = s.id
  editingTitle.value = s.title || ''
}

const cancelEditSession = (): void => {
  editingSessionId.value = null
  editingTitle.value = ''
}

const saveEditSession = async (id: number): Promise<void> => {
  const title = editingTitle.value.trim()
  if (!title) return
  const res = await fetch(`/api/v1/sessions/${id}`, {
    method: 'PATCH',
    headers: authHeaders(),
    body: JSON.stringify({ title }),
  })
  if (res.ok) {
    editingSessionId.value = null
    editingTitle.value = ''
    await loadChatSessions()
  }
}

const archiveSession = async (id: number, e: Event): Promise<void> => {
  e.stopPropagation()
  if (isWaiting.value || !window.confirm('确定归档该会话？归档后将从列表中隐藏。')) return
  const res = await fetch(`/api/v1/sessions/${id}`, { method: 'DELETE', headers: authHeaders() })
  if (!res.ok) return
  if (sessionId.value === id) {
    sessionId.value = null
    messages.value = []
  }
  await loadChatSessions()
  if (!sessionId.value && chatSessions.value.length) {
    await switchSession(chatSessions.value[0].id)
  }
}

const scrollToBottom = async (): Promise<void> => {
  await nextTick()
  const container = document.getElementById('chatContainer')
  if (container) container.scrollTop = container.scrollHeight
}

const adjustTextareaHeight = (e: Event): void => {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`
}

const uploadOneFile = async (file: File): Promise<{ path: string; name: string }> => {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/v1/multimodal/upload', { method: 'POST', headers: bearerOnly(), body: fd })
  const data = await res.json()
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '上传失败')
  return { path: data.path as string, name: (data.name as string) || file.name }
}

const queueUpload = (item: ChatPendingUpload): void => {
  if (pendingUploads.value.length >= MAX_PENDING_UPLOADS) {
    alert(`最多同时添加 ${MAX_PENDING_UPLOADS} 个附件`)
    return
  }
  pendingUploads.value.push(item)
  void startUpload(item)
}

const startUpload = async (item: ChatPendingUpload): Promise<void> => {
  if (!item.file) return
  item.uploading = true
  item.error = undefined
  try {
    const j = await uploadOneFile(item.file)
    item.path = j.path
    item.name = j.name
  } catch (e) {
    item.error = (e as Error).message || '上传失败'
  } finally {
    item.uploading = false
  }
}

const pickImages = (e: Event): void => {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  files.forEach((f) => {
    const reader = new FileReader()
    reader.onload = (ev) => {
      queueUpload({
        type: 'image',
        name: f.name,
        preview: String(ev.target?.result || ''),
        file: f,
      })
    }
    reader.readAsDataURL(f)
  })
  input.value = ''
}

const pickFiles = (e: Event): void => {
  const input = e.target as HTMLInputElement
  Array.from(input.files || []).forEach((f) => {
    queueUpload({ type: 'file', name: f.name, file: f })
  })
  input.value = ''
}

const removeUpload = (index: number): void => {
  pendingUploads.value.splice(index, 1)
}

const readyAttachments = (): ChatAttachment[] =>
  pendingUploads.value
    .filter((u) => u.path && !u.error)
    .map((u) => ({
      type: u.type,
      name: u.name,
      path: u.path as string,
      preview: u.preview,
    }))

const sendMessage = async (forcedText?: string): Promise<void> => {
  const text = (forcedText ?? inputText.value).trim()
  const attachments = readyAttachments()
  if ((!text && !attachments.length) || isWaiting.value) return
  if (text.length > maxQuestionLength.value) {
    alert(`单次提问不能超过 ${maxQuestionLength.value} 字`)
    return
  }
  if (pendingUploads.value.some((u) => u.uploading)) {
    alert('附件上传中，请稍候')
    return
  }
  if (pendingUploads.value.some((u) => u.error)) {
    alert('请先移除上传失败的附件')
    return
  }
  await ensureSession()
  const displayContent = text || (attachments.length === 1 ? `[附件] ${attachments[0].name}` : `[${attachments.length} 个附件]`)
  messages.value.push({
    role: 'user',
    content: displayContent,
    image: attachments.find((a) => a.type === 'image' && a.preview)?.preview,
    attachments: attachments.length ? attachments : undefined,
  })
  if (!forcedText) {
    inputText.value = ''
    pendingUploads.value = []
  }
  isWaiting.value = true
  scrollToBottom()

  let streamAssistantMsg: ChatMessage | null = null
  const ensureAssistant = (): ChatMessage => {
    if (!streamAssistantMsg) {
      streamAssistantMsg = {
        role: 'assistant',
        content: '',
        intent: '',
        citations: [],
        ragPrefetchSlices: [],
        messageId: null,
        isStreaming: true,
      }
      messages.value.push(streamAssistantMsg)
    }
    return streamAssistantMsg
  }

  try {
    const res = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        session_id: sessionId.value,
        question: text,
        kb_id: selectedKbId.value || undefined,
        attachments: attachments.length ? attachments.map(({ type, name, path, preview }) => ({ type, name, path, preview })) : undefined,
      }),
    })
    if (!res.ok) {
      let detail = `对话请求失败（HTTP ${res.status}）`
      try {
        const err = await res.json()
        if (typeof err.detail === 'string') detail = err.detail
      } catch {
        /* ignore */
      }
      ensureAssistant().content = detail
      return
    }
    const reader = res.body?.getReader()
    if (!reader) throw new Error('stream unavailable')
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        let event = 'message'
        let dataLine = ''
        part.split('\n').forEach((line) => {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          if (line.startsWith('data:')) dataLine = line.slice(5).trim()
        })
        if (!dataLine) continue
        const data = JSON.parse(dataLine)
        const bot = ensureAssistant()
        if (event === 'meta') {
          bot.intent = data.intent
          bot.intentLabel = data.intent_label || data.intent
          bot.llmProvider = data.llm_provider
          bot.llmNodeName = data.llm_node_name
          bot.llmModel = data.llm_model
          if (data.pipeline) bot.pipeline = data.pipeline
        }
        if (event === 'citations') {
          bot.ragPrefetchSlices = data.slices || data.items || []
          bot.citations = data.items || []
        }
        if (event === 'token') {
          bot.content += data.content || ''
          scrollToBottom()
        }
        if (event === 'follow_ups') {
          const items = data.items
          bot.followUps = Array.isArray(items)
            ? items.map((x: unknown) => String(x).trim()).filter((x: string) => x.length > 0).slice(0, 3)
            : []
          scrollToBottom()
        }
        if (event === 'done') bot.messageId = data.assistant_message_id
      }
    }
    await loadChatSessions()
  } catch {
    const bot = ensureAssistant()
    bot.content = bot.content || '网络连接异常，请检查后端服务。'
  } finally {
    if (streamAssistantMsg) {
      const finished = streamAssistantMsg as ChatMessage
      finished.isStreaming = false
      hydrateMsgCitations(finished)
    }
    isWaiting.value = false
    scrollToBottom()
  }
}

const sendFromInput = (): void => {
  void sendMessage()
}

const onInputKeydown = (e: KeyboardEvent): void => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendFromInput()
  }
}

const sendFollowUp = (text: string): void => {
  const q = text.trim()
  if (!q || isWaiting.value) return
  sendMessage(q)
}

watch(() => [sessionQuery.value.page, sessionQuery.value.size], loadChatSessions)

onMounted(async () => {
  await loadChatConfig()
  await loadChatSessions()
  await loadPlatformHealth(false)
  await loadKbList()
  if (chatSessions.value.length) {
    await switchSession(chatSessions.value[0].id)
  } else {
    await ensureSession()
  }
})
</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden min-h-0">
    <div class="h-14 border-b border-[#363e42]/5 bg-white/90 backdrop-blur-md flex items-center gap-3 px-4 shrink-0 flex-wrap chat-topbar">
      <button
        type="button"
        class="chat-topbar-toggle"
        :title="sessionSidebarOpen ? '收起会话列表' : '展开会话列表'"
        @click="sessionSidebarOpen = !sessionSidebarOpen"
      >
        <i class="fas" :class="sessionSidebarOpen ? 'fa-chevron-left' : 'fa-chevron-right'"></i>
      </button>
      <h2 class="chat-topbar-title">{{ contextTitle }}</h2>
      <span v-if="sessionId" class="chat-topbar-session-id" title="当前会话编号">#{{ sessionId }}</span>
      <div class="health-bar" @click="healthOpen = !healthOpen">
        <span class="health-bar-title">健康检查</span>
        <span class="health-bar-summary" :class="health?.all_ok ? 'health-ok' : 'health-warn'">{{ healthSummary }}</span>
        <button type="button" class="health-refresh" @click.stop="loadPlatformHealth(true)">刷新</button>
        <span class="health-chevron" :class="{ open: healthOpen }">▾</span>
      </div>
      <div v-if="healthOpen" class="health-drop">
        <p v-if="health?.error" class="health-err">{{ health.error }}</p>
        <div v-for="it in health?.items || []" :key="it.id" class="health-row" :class="`health-row--${it.status}`">
          <span class="health-label">{{ it.label }}</span>
          <span class="health-status">{{ it.status === 'ok' ? '正常' : it.status === 'warn' ? '降级' : '异常' }}</span>
          <span v-if="it.latency_ms" class="health-lat">{{ it.latency_ms }}ms</span>
          <p v-if="it.error" class="health-err-line">{{ it.error }}</p>
        </div>
      </div>
    </div>

    <div class="flex flex-1 min-h-0 overflow-hidden session-layout">
      <aside
        class="session-sidebar border-r border-[#363e42]/8 bg-[#fafafa] flex flex-col shrink-0 transition-[width] duration-300 ease-out overflow-hidden"
        :class="sessionSidebarOpen ? 'w-[272px]' : 'w-0 border-r-0'"
      >
        <div class="session-sidebar-inner w-[272px] h-full flex flex-col">
          <div class="p-2.5 border-b border-[#363e42]/8 bg-white">
            <button
              type="button"
              class="w-full text-[13px] font-bold bg-[#363e42] text-white rounded-lg py-2.5"
              :disabled="isWaiting"
              @click="newSession"
            >
              + 新对话
            </button>
          </div>
          <div class="p-2 border-b border-[#363e42]/8 bg-white space-y-2">
            <div class="flex gap-1">
              <input
                v-model="sessionQuery.name"
                type="text"
                class="flex-1 text-[11px] border rounded-lg px-2 py-1.5"
                placeholder="名称/ID 查询"
                @keyup.enter="sessionQuery.page = 1; loadChatSessions()"
              />
              <button type="button" class="text-[10px] px-2 rounded-lg border font-bold" @click="sessionQuery.page = 1; loadChatSessions()">查</button>
            </div>
            <div v-if="sessionSearchOpen" class="grid grid-cols-2 gap-1 text-[10px]">
              <input v-model="sessionQuery.id" type="text" placeholder="会话 ID" class="border rounded px-2 py-1" />
              <input v-model="sessionQuery.keyword" type="text" placeholder="关键词" class="border rounded px-2 py-1" />
              <input v-model="sessionQuery.dateFrom" type="date" class="border rounded px-1 py-1 col-span-1" />
              <input v-model="sessionQuery.dateTo" type="date" class="border rounded px-1 py-1 col-span-1" />
              <button type="button" class="col-span-2 text-[10px] border rounded py-1" @click="resetSessionSidebarQuery">重置</button>
            </div>
            <button type="button" class="text-[10px] text-[#64748b] font-bold" @click="sessionSearchOpen = !sessionSearchOpen">
              {{ sessionSearchOpen ? '收起筛选 ▲' : '更多筛选 ▼' }}
            </button>
          </div>
          <div class="flex-1 overflow-y-auto min-h-0">
            <div
              v-for="s in chatSessions"
              :key="s.id"
              class="session-item border-b border-[#363e42]/6 transition-colors group"
              :class="sessionId === s.id ? 'session-item--active' : ''"
            >
              <div
                v-if="editingSessionId !== s.id"
                class="px-3 py-3 cursor-pointer"
                @click="switchSession(s.id)"
              >
                <div class="flex items-start justify-between gap-2 mb-2">
                  <div class="session-item-title truncate flex-1">
                    {{ s.title || `会话 #${s.id}` }}
                  </div>
                  <div class="session-item-actions shrink-0" :class="sessionId === s.id ? 'opacity-100' : ''">
                    <button type="button" class="session-action-btn" title="重命名" @click="startEditSession(s, $event)">重命名</button>
                    <button type="button" class="session-action-btn session-action-btn--danger" title="归档" @click="archiveSession(s.id, $event)">归档</button>
                  </div>
                </div>
                <div class="session-item-meta">
                  <div class="session-meta-line">
                    <span class="session-meta-k">会话</span><span class="session-meta-v">#{{ s.id }}</span>
                  </div>
                  <div class="session-meta-line">
                    <span class="session-meta-k">更新</span><span class="session-meta-v strong">{{ fmtDateShort(s.updated_at) }}</span>
                    <span class="session-meta-dot">·</span>
                    <span class="session-meta-k">创建</span><span class="session-meta-v">{{ fmtDateShort(s.created_at) }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="px-3 py-3 flex flex-col gap-2 bg-white" @click.stop>
                <input v-model="editingTitle" class="w-full border border-[#363e42]/15 rounded-lg px-3 py-2 text-[13px]" maxlength="200" />
                <div class="flex gap-2">
                  <button type="button" class="flex-1 text-[12px] font-bold bg-[#363e42] text-white rounded-lg py-2" @click="saveEditSession(s.id)">保存</button>
                  <button type="button" class="flex-1 text-[12px] font-bold border border-[#363e42]/15 rounded-lg py-2" @click="cancelEditSession">取消</button>
                </div>
              </div>
            </div>
            <p v-if="!chatSessions.length" class="p-6 text-center text-[13px] text-[#4b5563]">暂无会话</p>
          </div>
          <ListPagination
            v-model:page="sessionQuery.page"
            v-model:size="sessionQuery.size"
            :total="sessionTotal"
            class="session-sidebar-pager shrink-0"
          />
        </div>
      </aside>

      <div class="flex-1 flex flex-col min-w-0 overflow-hidden session-main">
        <div id="chatContainer" class="flex-1 overflow-y-auto p-4 md:p-6 flex flex-col gap-6 chat-scroll">
          <div v-if="messages.length === 0 && !isWaiting" class="h-full flex flex-col items-center justify-center text-[#363e42]/30">
            <p class="font-black tracking-widest uppercase text-xs text-[#363e42]">智能客服 Agent 已就绪</p>
            <p class="text-[11px] font-medium mt-2 opacity-50">基于 RAG 知识库问答，支持流式输出与引用溯源</p>
          </div>
          <div v-for="(msg, index) in messages" :key="index" class="flex w-full" :class="msg.role === 'user' ? 'justify-end' : 'justify-start'">
            <div
              v-if="msg.role === 'user'"
              class="max-w-[85%] p-4 rounded-2xl shadow-sm border border-[#363e42]/5 text-[13px] whitespace-pre-wrap bg-[#d97706]/10"
            >
              <div v-if="msg.image || (msg.attachments && msg.attachments.length)" class="chat-user-attachments">
                <img v-if="msg.image" :src="msg.image" alt="" class="chat-user-attach-img" />
                <div v-for="(att, ai) in (msg.attachments || []).filter((a) => a.type === 'file')" :key="ai" class="chat-user-attach-file">
                  <i class="fas fa-file-alt"></i> {{ att.name }}
                </div>
              </div>
              <div v-if="msg.content">{{ msg.content }}</div>
            </div>
            <div
              v-else
              class="max-w-[85%] p-4 rounded-2xl shadow-sm border border-[#363e42]/5 text-[13px] bg-white"
            >
              <ChatAssistantMessage
                :msg="msg"
                :user-question="messages[index - 1]?.role === 'user' ? messages[index - 1].content : ''"
                :session-id="sessionId"
                :context-id="currentContextId"
                :context-summary="buildContextSummary(index)"
                @follow-up="sendFollowUp"
              />
            </div>
          </div>
          <div v-if="isWaiting" class="flex justify-start">
            <div class="p-4 rounded-2xl bg-white border shadow-sm">
              <div class="wave-loader"><div class="wave-dot"></div><div class="wave-dot"></div><div class="wave-dot"></div></div>
            </div>
          </div>
        </div>
        <div class="p-4 bg-white/80 border-t shrink-0">
          <div class="max-w-4xl mx-auto flex flex-col gap-1">
            <div v-if="pendingUploads.length" class="chat-upload-preview">
              <div v-for="(u, ui) in pendingUploads" :key="ui" class="chat-up-item" :class="u.type">
                <img v-if="u.preview" :src="u.preview" alt="" />
                <span v-else class="chat-up-file-name"><i class="fas fa-file-alt"></i> {{ u.name }}</span>
                <span v-if="u.uploading" class="chat-up-status">上传中…</span>
                <span v-else-if="u.error" class="chat-up-status chat-up-error">{{ u.error }}</span>
                <button type="button" class="chat-up-rm" title="移除" @click="removeUpload(ui)">&times;</button>
              </div>
            </div>
            <div v-if="kbList.length > 0" class="kb-selector-row mb-2">
              <label class="text-[11px] font-bold text-[#363e42]/60 flex items-center gap-2">
                <span>检索知识库</span>
                <select v-model="selectedKbId" class="border rounded-lg px-2 py-1 text-[11px] font-medium min-w-[140px]">
                  <option :value="null">全部知识库</option>
                  <option v-for="kb in kbList" :key="kb.id" :value="kb.id">{{ kb.name }} ({{ kb.doc_count }}篇)</option>
                </select>
              </label>
            </div>
            <div class="chat-input-row">
              <textarea
                v-model="inputText"
                rows="1"
                :maxlength="maxQuestionLength"
                class="chat-input-textarea"
                placeholder="输入消息，Enter 发送，Shift+Enter 换行"
                @keydown="onInputKeydown"
                @input="adjustTextareaHeight"
              />
              <div class="chat-input-tools">
                <label class="chat-itool" title="上传图片">
                  <input ref="imageInputRef" type="file" accept="image/*" multiple class="hidden" @change="pickImages" />
                  <span class="chat-itool-ic" aria-hidden="true">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
                  </span>
                </label>
                <label class="chat-itool" title="上传文件">
                  <input ref="fileInputRef" type="file" multiple accept=".pdf,.doc,.docx,.md,.txt,.markdown,.csv,.png,.jpg,.jpeg,.webp,.xls,.xlsx" class="hidden" @change="pickFiles" />
                  <span class="chat-itool-ic" aria-hidden="true">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  </span>
                </label>
                <button type="button" :disabled="!canSend" class="chat-send-btn" title="发送" @click="sendFromInput">
                  <i class="fas fa-paper-plane text-[13px]"></i>
                </button>
              </div>
            </div>
            <div class="text-right text-[12px] text-[#363e42]/65 px-1" :class="inputCharCount > maxQuestionLength ? 'text-red-500' : ''">
              {{ inputCharCount }} / {{ maxQuestionLength }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
