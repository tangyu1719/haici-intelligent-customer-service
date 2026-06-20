<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { authHeaders, getAccessToken } from '../api/auth'
import ChatAssistantMessage from './ChatAssistantMessage.vue'
import ListPagination from './ListPagination.vue'
import { hydrateMsgCitations } from '../utils/ragCitations'
import { INTENT_LABELS } from '../utils/intentLabels'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../utils/listQuery'
import { useSpeechInput } from '../utils/useSpeechInput'
import type { ChatAttachment, ChatFaqItem, ChatMessage, ChatPendingUpload, ChatSessionItem, KnowledgeBaseBrief, PlatformHealthSnapshot } from '../types'

const bearerOnly = (): Record<string, string> => {
  const t = getAccessToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

const MAX_PENDING_UPLOADS = 6
const LAST_SESSION_KEY = 'hc_last_chat_session_id'
const STREAM_DRAFT_PREFIX = 'hc_chat_stream_draft_'

type StreamDraft = {
  sessionId: number
  content: string
  intent?: string
  intentLabel?: string
  updatedAt: number
}

const streamDraftKey = (sid: number): string => `${STREAM_DRAFT_PREFIX}${sid}`

const saveStreamDraft = (sid: number | null, msg: ChatMessage): void => {
  if (!sid) return
  const text = (msg.content || '').trim()
  if (!text || text.startsWith('正在')) return
  const payload: StreamDraft = {
    sessionId: sid,
    content: msg.content,
    intent: msg.intent,
    intentLabel: msg.intentLabel,
    updatedAt: Date.now(),
  }
  sessionStorage.setItem(streamDraftKey(sid), JSON.stringify(payload))
}

const clearStreamDraft = (sid: number | null): void => {
  if (!sid) return
  sessionStorage.removeItem(streamDraftKey(sid))
}

/** 刷新页面后：若 DB 尚未落库，用本地草稿补回被截断的回答 */
const applyStreamDraftIfAny = (sid: number): void => {
  const raw = sessionStorage.getItem(streamDraftKey(sid))
  if (!raw) return
  try {
    const draft = JSON.parse(raw) as StreamDraft
    if (draft.sessionId !== sid) return
    const draftContent = (draft.content || '').trim()
    if (!draftContent) {
      clearStreamDraft(sid)
      return
    }
    const last = messages.value[messages.value.length - 1]
    if (last?.role === 'assistant' && (last.content || '').trim().length >= draftContent.length) {
      clearStreamDraft(sid)
      return
    }
    const restored: ChatMessage = {
      role: 'assistant',
      content: draftContent,
      intent: draft.intent || '',
      intentLabel: draft.intentLabel || draft.intent || '',
      citations: [],
      ragPrefetchSlices: [],
      messageId: null,
      isStreaming: false,
      streamInterrupted: true,
    }
    if (last?.role === 'assistant' && !(last.content || '').trim()) {
      messages.value[messages.value.length - 1] = restored
    } else if (last?.role !== 'assistant') {
      messages.value.push(restored)
    }
    hydrateMsgCitations(restored)
    clearStreamDraft(sid)
  } catch {
    clearStreamDraft(sid)
  }
}

const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const isWaiting = ref(false)
/** 后台轮询补全回答，不应阻塞侧栏切换/删除 */
const isPollingSession = ref(false)
let activeStreamAssistant: ChatMessage | null = null
let streamAbortController: AbortController | null = null
let switchSessionToken = 0
const sessionId = ref<number | null>(null)
let persistTimer: ReturnType<typeof setInterval> | null = null
let persistIntervalMinutes = 10
const chatSessions = ref<ChatSessionItem[]>([])
const sessionTotal = ref(0)
const sessionQuery = ref<ListQueryState>({ ...defaultListQuery(10), sortBy: 'updated_at', sortOrder: 'desc' })
const sessionSearchOpen = ref(false)
const health = ref<PlatformHealthSnapshot | null>(null)
const healthLoading = ref(false)
const healthOpen = ref(false)
const sessionSidebarOpen = ref(true)
const editingSessionId = ref<number | null>(null)
const editingTitle = ref('')
const maxQuestionLength = ref(500)
const dailyQuota = ref({
  limit: 100,
  used: 0,
  remaining: 100,
  unlimited: false,
})
const kbList = ref<KnowledgeBaseBrief[]>([])
const selectedKbId = ref<number | null>(null)
const faqItems = ref<ChatFaqItem[]>([])
const pendingUploads = ref<ChatPendingUpload[]>([])
const imageInputRef = ref<HTMLInputElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const inputTextareaRef = ref<HTMLTextAreaElement | null>(null)
let sessionPollTimer: ReturnType<typeof setInterval> | null = null

const resizeInputTextarea = (): void => {
  void nextTick(() => {
    const el = inputTextareaRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  })
}

const speechInput = useSpeechInput({
  lang: 'zh-CN',
  onText: (text) => {
    inputText.value = text.slice(0, maxQuestionLength.value)
    resizeInputTextarea()
  },
})

const toggleVoiceInput = (): void => {
  if (isWaiting.value) return
  speechInput.toggle(inputText.value)
}

const inputCharCount = computed(() => inputText.value.length)
const canSend = computed(() => {
  if (isWaiting.value) return false
  const hasText = inputText.value.trim().length > 0
  const hasReadyUpload = pendingUploads.value.some((u) => u.path && !u.uploading && !u.error)
  const uploading = pendingUploads.value.some((u) => u.uploading)
  return (hasText || hasReadyUpload) && !uploading
})

/** 已有流式助手气泡时不重复显示底部 wave-loader */
const showStreamWaiting = computed(
  () =>
    (isWaiting.value || isPollingSession.value)
    && !messages.value.some((m) => m.role === 'assistant' && m.isStreaming),
)

const fmtDateShort = (s?: string): string => {
  if (!s) return '-'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const contextTitle = computed(() => {
  if (!sessionId.value) return '请选择或新建对话'
  const cur = chatSessions.value.find((s) => s.id === sessionId.value)
  const t = (cur?.title || '').trim()
  return t && t !== '新对话' ? t : `会话 #${sessionId.value}`
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
  const parts = [`${s.ok} 正常`]
  if ((s.warn ?? 0) > 0) parts.push(`${s.warn} 降级`)
  if ((s.error ?? 0) > 0) parts.push(`${s.error} 异常`)
  return parts.join(' · ')
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
      const limit = data.daily_question_limit ?? 100
      const used = data.daily_questions_used ?? 0
      const remaining =
        data.daily_questions_remaining ?? Math.max(0, limit - used)
      dailyQuota.value = {
        limit,
        used,
        remaining,
        unlimited: !!data.daily_quota_unlimited,
      }
      faqItems.value = Array.isArray(data.faq_items) ? data.faq_items : []
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

const saveLastSession = (id: number): void => {
  localStorage.setItem(LAST_SESSION_KEY, String(id))
}

const pickPreferredSession = (): ChatSessionItem | undefined => {
  if (!chatSessions.value.length) return undefined
  const savedId = Number(localStorage.getItem(LAST_SESSION_KEY) || 0)
  if (savedId) {
    const saved = chatSessions.value.find((s) => s.id === savedId)
    if (saved && (saved.message_count ?? 0) > 0) return saved
  }
  return (
    chatSessions.value.find((s) => (s.message_count ?? 0) > 0)
    ?? chatSessions.value[0]
  )
}

const restoreInitialSession = async (): Promise<void> => {
  const target = pickPreferredSession()
  if (!target) {
    sessionId.value = null
    messages.value = []
    return
  }
  await switchSession(target.id)
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
  saveLastSession(sessionId.value)
  await loadChatSessions()
  return sessionId.value as number
}

const loadSessionMessages = async (id: number): Promise<void> => {
  const qs = toSearchParams({ ...defaultListQuery(100), sortBy: 'created_at', sortOrder: 'asc', page: 1, keyword: '', dateFrom: '', dateTo: '', id: '', name: '' })
  const res = await fetch(`/api/v1/sessions/${id}/messages?${qs}`, { headers: authHeaders() })
  if (!res.ok) {
    const fallback = await fetch(`/api/v1/sessions/${id}`, { headers: authHeaders() })
    if (!fallback.ok) return
    const data = await fallback.json()
    messages.value = mapHistoryMessages(data.messages || [])
    applyStreamDraftIfAny(id)
    return
  }
  const data = await res.json()
  messages.value = mapHistoryMessages(data.items || [])
  applyStreamDraftIfAny(id)
  scrollToBottom()
}

const stopSessionPoll = (): void => {
  if (sessionPollTimer) {
    clearInterval(sessionPollTimer)
    sessionPollTimer = null
  }
  isPollingSession.value = false
}

/** 切换/删除会话时取消进行中的流式与轮询，避免侧栏被 isWaiting 锁死 */
const cancelOngoingChat = (): void => {
  if (streamAbortController) {
    streamAbortController.abort()
    streamAbortController = null
  }
  stopSessionPoll()
  isWaiting.value = false
  if (activeStreamAssistant) {
    activeStreamAssistant.isStreaming = false
    activeStreamAssistant = null
  }
}

const sessionNeedsPoll = (sid: number): boolean => {
  const cur = chatSessions.value.find((s) => s.id === sid)
  if (cur?.meta?.streaming) return true
  const last = messages.value[messages.value.length - 1]
  return !!last && last.role === 'user'
}

/** 后台仍在生成时轮询 DB，刷新/切页回来后自动补全回答 */
const pollSessionUntilReady = (sid: number): void => {
  stopSessionPoll()
  if (!sessionNeedsPoll(sid) || sessionId.value !== sid) return
  isPollingSession.value = true
  let attempts = 0
  sessionPollTimer = setInterval(async () => {
    if (sessionId.value !== sid) {
      stopSessionPoll()
      return
    }
    attempts += 1
    await loadSessionMessages(sid)
    await loadChatSessions()
    if (!sessionNeedsPoll(sid) || attempts >= 45 || sessionId.value !== sid) {
      stopSessionPoll()
      scrollToBottom()
    }
  }, 2000)
}

const mapHistoryMessages = (rows: { role: string; content: string; intent_label?: string; citations?: unknown; id: number; created_at?: string }[]): ChatMessage[] =>
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
      createdAt: m.created_at,
      isStreaming: false,
      followUps: [],
    }
    if (msg.role === 'assistant') hydrateMsgCitations(msg)
    return msg
  })

/** 规范化 SSE 追问建议并写入助手消息 */
const applyFollowUps = (bot: ChatMessage, items: unknown): void => {
  const normalized = (Array.isArray(items) ? items : [])
    .map((x) => String(x).trim())
    .filter((x) => x.length > 0)
    .slice(0, 3)
  if (normalized.length) bot.followUps = normalized
}

const switchSession = async (id: number): Promise<void> => {
  if (sessionId.value === id) return
  cancelOngoingChat()
  speechInput.stop()
  const token = ++switchSessionToken
  const prev = sessionId.value
  if (prev && prev !== id) {
    void syncSessionToDb(prev, 'switch')
  }
  sessionId.value = id
  saveLastSession(id)
  await loadSessionMessages(id)
  if (token !== switchSessionToken) return
  pollSessionUntilReady(id)
  restartPersistTimer()
}

const syncSessionToDb = async (sid: number, reason = 'interval'): Promise<void> => {
  try {
    await fetch(`/api/v1/sessions/${sid}/sync`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ reason }),
    })
  } catch {
    /* 静默失败，下次间隔重试 */
  }
}

const stopPersistTimer = (): void => {
  if (persistTimer) {
    clearInterval(persistTimer)
    persistTimer = null
  }
}

const restartPersistTimer = (): void => {
  stopPersistTimer()
  if (!sessionId.value) return
  const ms = Math.max(60_000, persistIntervalMinutes * 60_000)
  persistTimer = setInterval(() => {
    if (sessionId.value) void syncSessionToDb(sessionId.value, 'interval')
  }, ms)
}

const loadPersistInterval = async (): Promise<void> => {
  try {
    const res = await fetch('/api/v1/sessions/settings/persist-interval', { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      persistIntervalMinutes = data.session_active_persist_interval_minutes ?? 10
    }
  } catch {
    persistIntervalMinutes = 10
  }
}

const newSession = async (): Promise<void> => {
  cancelOngoingChat()
  speechInput.stop()
  switchSessionToken += 1
  const prev = sessionId.value
  if (prev) void syncSessionToDb(prev, 'switch')
  const res = await fetch('/api/v1/sessions', { method: 'POST', headers: authHeaders() })
  if (!res.ok) return
  const data = await res.json()
  sessionId.value = data.id
  messages.value = []
  saveLastSession(data.id as number)
  editingSessionId.value = null
  await loadChatSessions()
  restartPersistTimer()
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
  if (!window.confirm('确定删除该会话？删除后将从您的列表中隐藏，管理员仍可在「会话审计」中查看完整记录。')) return
  if (sessionId.value === id) {
    cancelOngoingChat()
    switchSessionToken += 1
    sessionId.value = null
    messages.value = []
  }
  const res = await fetch(`/api/v1/sessions/${id}`, { method: 'DELETE', headers: authHeaders() })
  if (!res.ok) {
    window.alert('删除失败，请稍后重试')
    return
  }
  await loadChatSessions()
  if (!sessionId.value && chatSessions.value.length) {
    const next = pickPreferredSession()
    if (next) await switchSession(next.id)
  }
}

const showScrollBtn = ref(false)

const onChatScroll = (): void => {
  const container = document.getElementById('chatContainer')
  if (!container) return
  showScrollBtn.value = container.scrollHeight - container.scrollTop - container.clientHeight > 120
}

const scrollToBottom = async (): Promise<void> => {
  await nextTick()
  const container = document.getElementById('chatContainer')
  if (container) {
    container.scrollTop = container.scrollHeight
    showScrollBtn.value = false
  }
}

const adjustTextareaHeight = (e: Event): void => {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  if (speechInput.error.value) speechInput.error.value = ''
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
  isWaiting.value = true
  speechInput.stop()
  await ensureSession()
  const displayContent = text || (attachments.length === 1 ? `[附件] ${attachments[0].name}` : `[${attachments.length} 个附件]`)
  messages.value.push({
    role: 'user',
    content: displayContent,
    image: attachments.find((a) => a.type === 'image' && a.preview)?.preview,
    attachments: attachments.length ? attachments : undefined,
    createdAt: new Date().toISOString(),
  })
  if (!forcedText) {
    inputText.value = ''
    pendingUploads.value = []
  }
  scrollToBottom()

  let streamAssistantMsg: ChatMessage | null = null
  let streamDone = false
  const pendingTokenChunks: string[] = []
  const pendingThinkChunks: string[] = []
  let tokenFlushScheduled = false
  let thinkFlushScheduled = false
  activeStreamAssistant = null
  const ensureAssistant = (): ChatMessage => {
    if (!streamAssistantMsg) {
      streamAssistantMsg = reactive({
        role: 'assistant',
        content: '',
        intent: '',
        citations: [],
        ragPrefetchSlices: [],
        thinkContent: '',
        isThinking: false,
        thinkCollapsed: false,
        phaseStatus: '',
        retrievalCount: 0,
        reactSteps: [],
        reactMode: false,
        messageId: null,
        isStreaming: true,
        followUps: [],
      } as ChatMessage)
      messages.value.push(streamAssistantMsg)
      activeStreamAssistant = streamAssistantMsg
    }
    return streamAssistantMsg
  }

  const flushPendingTokens = (forceAll = false): void => {
    tokenFlushScheduled = false
    const bot = streamAssistantMsg
    if (!bot || pendingTokenChunks.length === 0) return
    if (forceAll) {
      bot.content += pendingTokenChunks.join('')
      pendingTokenChunks.length = 0
      saveStreamDraft(sessionId.value, bot)
      scrollToBottom()
      return
    }
    // 每帧吐出一小段，即使代理一次性送达也能看到打字效果
    let budget = 16
    while (pendingTokenChunks.length > 0 && budget > 0) {
      const head = pendingTokenChunks[0]
      if (head.length <= budget) {
        bot.content += head
        budget -= head.length
        pendingTokenChunks.shift()
      } else {
        bot.content += head.slice(0, budget)
        pendingTokenChunks[0] = head.slice(budget)
        budget = 0
      }
    }
    saveStreamDraft(sessionId.value, bot)
    scrollToBottom()
    if (pendingTokenChunks.length > 0) scheduleTokenFlush()
  }

  const scheduleTokenFlush = (): void => {
    if (tokenFlushScheduled) return
    tokenFlushScheduled = true
    requestAnimationFrame(() => flushPendingTokens(false))
  }

  const flushPendingThink = (forceAll = false): void => {
    thinkFlushScheduled = false
    const bot = streamAssistantMsg
    if (!bot || pendingThinkChunks.length === 0) return
    if (forceAll) {
      bot.thinkContent = (bot.thinkContent || '') + pendingThinkChunks.join('')
      pendingThinkChunks.length = 0
      scrollToBottom()
      return
    }
    let budget = 24
    while (pendingThinkChunks.length > 0 && budget > 0) {
      const head = pendingThinkChunks[0]
      if (head.length <= budget) {
        bot.thinkContent = (bot.thinkContent || '') + head
        budget -= head.length
        pendingThinkChunks.shift()
      } else {
        bot.thinkContent = (bot.thinkContent || '') + head.slice(0, budget)
        pendingThinkChunks[0] = head.slice(budget)
        budget = 0
      }
    }
    scrollToBottom()
    if (pendingThinkChunks.length > 0) scheduleThinkFlush()
  }

  const scheduleThinkFlush = (): void => {
    if (thinkFlushScheduled) return
    thinkFlushScheduled = true
    requestAnimationFrame(() => flushPendingThink(false))
  }

  const appendStreamToken = (bot: ChatMessage, piece: string): void => {
    const token = String(piece || '')
    if (!token) return
    flushPendingThink(true)
    if (bot.thinkContent && !bot.thinkCollapsed) {
      bot.thinkCollapsed = true
    }
    bot.isThinking = false
    bot.phaseStatus = ''
    pendingTokenChunks.push(token)
    scheduleTokenFlush()
  }

  const appendThinkToken = (bot: ChatMessage, piece: string): void => {
    const token = String(piece || '')
    if (!token) return
    bot.isThinking = true
    bot.thinkCollapsed = false
    pendingThinkChunks.push(token)
    scheduleThinkFlush()
  }

  // 立刻展示助手气泡与阶段提示，避免长时间只有底部 loading
  const starter = ensureAssistant()
  starter.phaseStatus = '正在理解…'
  starter.content = ''

  streamAbortController = new AbortController()
  const streamSid = sessionId.value
  const streamSignal = streamAbortController.signal
  try {
    const res = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      cache: 'no-store',
      signal: streamSignal,
      headers: {
        ...authHeaders(),
        Accept: 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
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
      if (res.status === 409 && sessionId.value) {
        pollSessionUntilReady(sessionId.value)
        return
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
        if (!part.trim() || part.trimStart().startsWith(':')) continue
        let event = 'message'
        let dataLine = ''
        part.split('\n').forEach((line) => {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          if (line.startsWith('data:')) dataLine = line.slice(5).trim()
        })
        if (!dataLine) continue
        const data = JSON.parse(dataLine)
        const bot = ensureAssistant()
        if (event === 'status') {
          const phase = String(data.phase || '')
          if (phase === 'retrieval_done') {
            bot.retrievalCount = Number(data.count ?? bot.retrievalCount ?? 0)
            bot.phaseStatus = ''
          } else if (phase === 'thinking') {
            bot.phaseStatus = ''
          } else if (phase === 'generating') {
            bot.phaseStatus = ''
          } else if (phase === 'follow_ups') {
            bot.phaseStatus = data.text || '正在生成追问建议…'
          } else if (!bot.ragPrefetchSlices?.length && !(bot.content || '').trim()) {
            bot.phaseStatus = data.text || ''
          }
        }
        if (event === 'meta') {
          bot.intent = data.intent
          bot.intentLabel = data.intent_label || data.intent
          bot.llmProvider = data.llm_provider
          bot.llmNodeName = data.llm_node_name
          bot.llmModel = data.llm_model
          if (data.pipeline) bot.pipeline = data.pipeline
          if (data.react_mode) bot.reactMode = true
        }
        if (event === 'react_step') {
          bot.reactMode = true
          if (!bot.reactSteps) bot.reactSteps = []
          const stepNum = Number(data.step || 0)
          const phase = String(data.phase || 'thought') as 'thought' | 'act' | 'observe'
          let stepRec = bot.reactSteps.find((s) => s.step === stepNum && s.phase === phase)
          if (!stepRec) {
            stepRec = { step: stepNum, phase, content: '', streaming: Boolean(data.streaming) }
            if (data.tool) stepRec.tool = String(data.tool)
            if (data.tool_query) stepRec.toolQuery = String(data.tool_query)
            bot.reactSteps.push(stepRec)
          }
          if (phase === 'thought' && data.kind === 'think' && data.content) {
            appendThinkToken(bot, data.content)
          } else if (data.streaming && data.content) {
            stepRec.content = (stepRec.content || '') + String(data.content)
            stepRec.streaming = true
          }
          if (data.done) {
            stepRec.content = String(data.content || stepRec.content || '')
            stepRec.streaming = false
            if (data.slice_count != null) stepRec.sliceCount = Number(data.slice_count)
          }
          if (data.tool_query) stepRec.toolQuery = String(data.tool_query)
          scrollToBottom()
        }
        if (event === 'intent') {
          bot.intent = data.intent || bot.intent
          bot.intentLabel = data.intent_label || data.intent || bot.intentLabel
          if (data.source) {
            bot.pipeline = { ...(bot.pipeline || {}), source: data.source }
          }
        }
        if (event === 'think') {
          appendThinkToken(bot, data.content || '')
          scrollToBottom()
        }
        if (event === 'cached') {
          flushPendingThink(true)
          pendingTokenChunks.length = 0
          tokenFlushScheduled = false
          const text = String(data.content || '')
          bot.content = text
          bot.isCachedReply = true
          bot.cachedSource = String(data.source || '')
          bot.isStreaming = false
          bot.phaseStatus = ''
          saveStreamDraft(sessionId.value, bot)
          scrollToBottom()
        }
        if (event === 'token') {
          bot.isCachedReply = false
          appendStreamToken(bot, data.content || '')
        }
        if (event === 'citations') {
          bot.ragPrefetchSlices = data.slices || data.items || []
          bot.citations = data.items || []
          hydrateMsgCitations(bot)
          bot.retrievalCount = bot.ragCitationSlices?.length ?? bot.ragPrefetchSlices?.length ?? 0
          bot.phaseStatus = ''
          scrollToBottom()
        }
        if (event === 'follow_ups') {
          applyFollowUps(bot, data.items)
          scrollToBottom()
        }
        if (event === 'done') {
          flushPendingThink(true)
          flushPendingTokens(true)
          streamDone = true
          bot.isThinking = false
          if (bot.thinkContent) bot.thinkCollapsed = true
          bot.phaseStatus = ''
          bot.messageId = data.assistant_message_id
          applyFollowUps(bot, data.follow_ups ?? data.items)
          bot.isStreaming = false
          const finalText = String(data.content || '').trim()
          if (finalText && (!bot.content || bot.content.startsWith('正在'))) {
            bot.content = finalText
          } else if (finalText && finalText.length > (bot.content || '').length) {
            bot.content = finalText
          }
          clearStreamDraft(sessionId.value)
          scrollToBottom()
        }
      }
    }
    if (sessionId.value === streamSid) {
      await loadChatSessions()
    }
  } catch (e) {
    if (streamSignal.aborted || sessionId.value !== streamSid) return
    const bot = ensureAssistant()
    if (!streamDone && (bot.content || '').trim() && !(bot.content || '').startsWith('正在')) {
      bot.streamInterrupted = true
      saveStreamDraft(sessionId.value, bot)
    } else if (!streamDone) {
      bot.content = '网络连接异常，请检查后端服务。'
    }
  } finally {
    if (streamAbortController?.signal === streamSignal) {
      streamAbortController = null
    }
    if (sessionId.value !== streamSid) return
    flushPendingThink(true)
    flushPendingTokens(true)
    if (streamAssistantMsg) {
      const finished = streamAssistantMsg as ChatMessage
      finished.isStreaming = false
      if (!streamDone && (finished.content || '').trim() && !(finished.content || '').startsWith('正在')) {
        finished.streamInterrupted = true
      }
      if (!finished.createdAt) finished.createdAt = new Date().toISOString()
      hydrateMsgCitations(finished)
    }
    isWaiting.value = false
    activeStreamAssistant = null
    scrollToBottom()
    void loadChatConfig()
    if (streamSid != null && sessionId.value === streamSid && sessionNeedsPoll(streamSid)) {
      pollSessionUntilReady(streamSid)
    }
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

const faqCategories = computed(() => {
  const cats = new Set<string>()
  for (const item of faqItems.value) {
    if (item.category) cats.add(item.category)
  }
  return Array.from(cats)
})

const faqByCategory = (category: string): ChatFaqItem[] =>
  faqItems.value.filter((item) => item.category === category)

const askFaq = (item: ChatFaqItem): void => {
  const q = (item?.question || '').trim()
  if (!q || isWaiting.value) return
  void sendMessage(q)
}

const regenerateReply = (userQuestion: string): void => {
  const q = userQuestion.trim()
  if (!q || isWaiting.value) return
  const last = messages.value[messages.value.length - 1]
  if (last?.role === 'assistant' && last.streamInterrupted) {
    messages.value.pop()
  }
  void sendMessage(q)
}

watch(() => [sessionQuery.value.page, sessionQuery.value.size], loadChatSessions)

onBeforeUnmount(() => {
  cancelOngoingChat()
  stopPersistTimer()
  if (sessionId.value) void syncSessionToDb(sessionId.value, 'exit')
  if (isWaiting.value && activeStreamAssistant && sessionId.value) {
    saveStreamDraft(sessionId.value, activeStreamAssistant)
  }
})

onMounted(async () => {
  await loadPersistInterval()
  await loadChatConfig()
  await loadChatSessions()
  await loadPlatformHealth(false)
  await loadKbList()
  await restoreInitialSession()
})
</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden min-h-0">
    <div class="flex flex-1 min-h-0 overflow-hidden session-layout">
      <aside
        class="session-sidebar border-r border-[#363e42]/8 bg-[#fafafa] flex flex-col shrink-0 transition-[width] duration-300 ease-out overflow-hidden"
        :class="sessionSidebarOpen ? 'w-[272px]' : 'w-0 border-r-0'"
      >
        <div class="session-sidebar-inner w-[272px] h-full flex flex-col">
          <div class="p-2.5 border-b border-[#363e42]/8 bg-white">
            <button
              type="button"
              class="w-full text-[11px] font-bold bg-[#363e42] text-white rounded-lg py-2"
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
              class="session-item-row px-2 py-2 cursor-pointer"
              @click="switchSession(s.id)"
            >
              <button
                type="button"
                class="session-delete-btn shrink-0"
                title="从界面删除（管理员仍可审计）"
                @click="archiveSession(s.id, $event)"
              >
                删除
              </button>
              <div class="session-item-main flex-1 min-w-0">
                <div class="flex items-start justify-between gap-2 mb-1">
                  <div class="session-item-title truncate flex-1">
                    {{ s.title || `会话 #${s.id}` }}
                  </div>
                  <div class="session-item-actions shrink-0" :class="sessionId === s.id ? 'opacity-100' : ''">
                    <button type="button" class="session-action-btn" title="重命名" @click="startEditSession(s, $event)">重命名</button>
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
            </div>
              <div v-else class="px-3 py-3 flex flex-col gap-2 bg-white" @click.stop>
                <input v-model="editingTitle" class="w-full border border-[#363e42]/15 rounded-lg px-3 py-2 text-[13px]" maxlength="200" />
                <div class="flex gap-2">
                  <button type="button" class="flex-1 text-[12px] font-bold bg-[#363e42] text-white rounded-lg py-2" @click="saveEditSession(s.id)">保存</button>
                  <button type="button" class="flex-1 text-[12px] font-bold border border-[#363e42]/15 rounded-lg py-2" @click="cancelEditSession">取消</button>
                </div>
              </div>
            </div>
            <p v-if="!chatSessions.length" class="p-4 text-center text-[11px] text-[#64748b]">暂无会话，点击上方新建</p>
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
        <div class="chat-topbar shrink-0">
          <button
            type="button"
            class="chat-topbar-toggle"
            :title="sessionSidebarOpen ? '收起会话列表' : '展开会话列表'"
            @click="sessionSidebarOpen = !sessionSidebarOpen"
          >
            <i class="fas" :class="sessionSidebarOpen ? 'fa-chevron-left' : 'fa-chevron-right'"></i>
          </button>
          <div class="chat-topbar-title-wrap">
            <h2 class="chat-topbar-title">{{ contextTitle }}</h2>
            <span v-if="sessionId" class="chat-topbar-session-id" title="当前会话编号">#{{ sessionId }}</span>
          </div>
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
        <div id="chatContainer" class="flex-1 overflow-y-auto p-4 md:p-6 flex flex-col gap-6 chat-scroll min-h-0 relative" @scroll="onChatScroll">
          <div v-if="messages.length === 0 && !isWaiting" class="chat-welcome">
            <div class="chat-welcome-head">
              <p class="chat-welcome-title">智能客服 Agent 已就绪</p>
              <p class="chat-welcome-desc">基于 RAG 知识库问答，支持流式输出与引用溯源</p>
            </div>
            <div v-if="faqItems.length" class="chat-faq-panel">
              <div class="chat-faq-panel-hd">
                <span class="chat-faq-panel-title">常见问题 FAQ</span>
                <span class="chat-faq-panel-hint">标准答案已缓存，点击即展示，无需等待检索</span>
              </div>
              <div v-for="cat in faqCategories" :key="cat" class="chat-faq-group">
                <div class="chat-faq-group-title">{{ cat }}</div>
                <div class="chat-faq-grid">
                  <button
                    v-for="item in faqByCategory(cat)"
                    :key="item.id"
                    type="button"
                    class="chat-faq-card"
                    :disabled="isWaiting"
                    @click="askFaq(item)"
                  >
                    <span class="chat-faq-q">{{ item.question }}</span>
                    <span class="chat-faq-a">{{ item.answer }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div v-for="(msg, index) in messages" :key="index" class="flex w-full min-w-0 flex-col" :class="msg.role === 'user' ? 'items-end' : 'items-start'">
            <div
              v-if="msg.role === 'user'"
              class="msg-bubble msg-bubble--user"
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
              class="w-full min-w-0 assistant-msg-column"
            >
              <ChatAssistantMessage
                :msg="msg"
                :user-question="messages[index - 1]?.role === 'user' ? messages[index - 1].content : ''"
                :session-id="sessionId"
                :context-id="currentContextId"
                :context-summary="buildContextSummary(index)"
                @follow-up="sendFollowUp"
                @regenerate="regenerateReply"
              />
            </div>
            <span class="msg-time" :class="msg.role === 'user' ? 'text-right' : ''">{{ fmtDateShort(msg.createdAt) }}</span>
          </div>
          <div v-if="showStreamWaiting" class="flex justify-start">
            <div class="p-4 rounded-2xl bg-white border shadow-sm">
              <div class="wave-loader"><div class="wave-dot"></div><div class="wave-dot"></div><div class="wave-dot"></div></div>
            </div>
          </div>
          <transition name="fade">
            <button
              v-if="showScrollBtn"
              type="button"
              class="scroll-bottom-btn"
              title="滚动到底部"
              @click="scrollToBottom"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
            </button>
          </transition>
        </div>
        <div class="p-4 bg-white/80 border-t shrink-0">
          <div class="w-full min-w-0 flex flex-col gap-1">
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
            <div class="chat-input-row" :class="{ 'chat-input-row--listening': speechInput.listening.value }">
              <textarea
                ref="inputTextareaRef"
                v-model="inputText"
                rows="1"
                :maxlength="maxQuestionLength"
                class="chat-input-textarea"
                :placeholder="speechInput.listening.value ? '正在聆听…' : '输入消息，Enter 发送，Shift+Enter 换行'"
                @keydown="onInputKeydown"
                @input="adjustTextareaHeight"
              />
              <div class="chat-input-tools">
                <button
                  v-if="speechInput.supported.value"
                  type="button"
                  class="chat-itool chat-itool--voice"
                  :class="{ 'is-listening': speechInput.listening.value }"
                  :title="speechInput.listening.value ? '停止语音输入' : '语音输入'"
                  :disabled="isWaiting"
                  @click="toggleVoiceInput"
                >
                  <span class="chat-itool-ic" aria-hidden="true">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
                      <path d="M19 10v2a7 7 0 01-14 0v-2" />
                      <line x1="12" y1="19" x2="12" y2="23" />
                      <line x1="8" y1="23" x2="16" y2="23" />
                    </svg>
                  </span>
                </button>
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
            <p v-if="speechInput.listening.value" class="chat-voice-status">正在聆听，再次点击麦克风可停止</p>
            <p v-else-if="speechInput.error.value" class="chat-voice-status chat-voice-status--error">{{ speechInput.error.value }}</p>
            <div class="flex items-center justify-between text-[12px] text-[#363e42]/65 px-1 gap-3">
              <span v-if="dailyQuota.unlimited" class="chat-quota-hint">今日已提问 {{ dailyQuota.used }} 次（管理员不限次）</span>
              <span v-else class="chat-quota-hint">
                今日提问 {{ dailyQuota.used }} / {{ dailyQuota.limit }}（剩余 {{ dailyQuota.remaining }}）
              </span>
              <span :class="inputCharCount > maxQuestionLength ? 'text-red-500' : ''">
                {{ inputCharCount }} / {{ maxQuestionLength }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
