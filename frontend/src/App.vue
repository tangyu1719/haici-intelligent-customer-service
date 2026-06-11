<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { authHeaders, getToken, setToken } from './api/client'
import type { ChatMessage, KnowledgeDoc } from './types'

const isSidebarOpen = ref(true)
const currentView = ref<'chat' | 'kb'>('chat')
const inputText = ref('')
const messages = ref<ChatMessage[]>([])
const isWaiting = ref(false)
const sessionId = ref<number | null>(null)
const token = ref(getToken())
const showLogin = ref(!token.value)
const loginAccount = ref('')
const loginPassword = ref('')
const kbDocs = ref<KnowledgeDoc[]>([])
const isRecording = ref(false)
let recognition: { start: () => void; stop: () => void } | null = null

const ensureSession = async (): Promise<number> => {
  if (sessionId.value) return sessionId.value
  const res = await fetch('/api/v1/sessions', { method: 'POST', headers: authHeaders() })
  const data = await res.json()
  sessionId.value = data.id
  return sessionId.value
}

const login = async (): Promise<void> => {
  const form = new URLSearchParams()
  form.set('username', loginAccount.value)
  form.set('password', loginPassword.value)
  const res = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  })
  if (!res.ok) {
    alert('登录失败')
    return
  }
  const data = await res.json()
  token.value = data.access_token
  setToken(token.value)
  showLogin.value = false
  await ensureSession()
  await loadKnowledge()
}

const register = async (): Promise<void> => {
  const body: Record<string, string> = { password: loginPassword.value }
  if (loginAccount.value.includes('@')) body.email = loginAccount.value
  else body.phone = loginAccount.value
  const res = await fetch('/api/v1/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    alert('注册失败')
    return
  }
  await login()
}

const loadKnowledge = async (): Promise<void> => {
  const res = await fetch('/api/v1/knowledge', { headers: authHeaders() })
  if (res.ok) kbDocs.value = await res.json()
}

const uploadKnowledge = async (event: Event): Promise<void> => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  await fetch('/api/v1/knowledge/upload', {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken()}` },
    body: fd,
  })
  input.value = ''
  await loadKnowledge()
}

const deleteKnowledge = async (id: number): Promise<void> => {
  await fetch(`/api/v1/knowledge/${id}`, { method: 'DELETE', headers: authHeaders() })
  await loadKnowledge()
}

const submitFeedback = async (messageId: number, rating: number): Promise<void> => {
  await fetch(`/api/v1/feedback/messages/${messageId}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ rating }),
  })
}

onMounted(async () => {
  if (token.value) {
    await ensureSession()
    await loadKnowledge()
  }
})

const toggleRecording = (): void => {
  if (!recognition) {
    alert('当前浏览器不支持语音识别')
    return
  }
  if (isRecording.value) recognition.stop()
  else recognition.start()
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

const sendMessage = async (): Promise<void> => {
  const text = inputText.value.trim()
  if (!text || isWaiting.value || !token.value) return
  if (text.length > 500) {
    alert('单次提问不能超过500字')
    return
  }
  await ensureSession()
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  isWaiting.value = true
  const assistant: ChatMessage = {
    role: 'assistant',
    content: '',
    intent: '',
    citations: [],
    messageId: null,
  }
  messages.value.push(assistant)
  scrollToBottom()
  try {
    const res = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ session_id: sessionId.value, question: text }),
    })
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
        if (event === 'meta') assistant.intent = data.intent
        if (event === 'citations') assistant.citations = data.items || []
        if (event === 'token') assistant.content += data.content || ''
        if (event === 'done') assistant.messageId = data.assistant_message_id
      }
      scrollToBottom()
    }
  } catch {
    assistant.content = '网络连接异常，请检查后端服务。'
  } finally {
    isWaiting.value = false
    scrollToBottom()
  }
}
</script>

<template>
  <div
    v-cloak
    class="flex h-full w-full bg-white rounded-[24px] border border-[#363e42]/5 shadow-[0_8px_30px_rgb(0,0,0,0.04)] overflow-hidden relative"
  >
    <div v-if="showLogin" class="absolute inset-0 z-50 bg-black/40 flex items-center justify-center">
      <div class="bg-white rounded-2xl p-6 w-[360px] shadow-xl">
        <h3 class="text-lg font-black mb-4">登录 / 注册</h3>
        <input v-model="loginAccount" class="w-full border rounded-lg p-2 mb-2" placeholder="邮箱或手机号" />
        <input v-model="loginPassword" type="password" class="w-full border rounded-lg p-2 mb-4" placeholder="密码（至少6位）" />
        <div class="flex gap-2">
          <button class="flex-1 bg-[#363e42] text-white py-2 rounded-lg" @click="login">登录</button>
          <button class="flex-1 bg-[#d97706] text-white py-2 rounded-lg" @click="register">注册</button>
        </div>
      </div>
    </div>

    <aside
      :class="isSidebarOpen ? 'w-[180px]' : 'w-[72px]'"
      class="h-full bg-white border-r border-[#363e42]/5 flex flex-col z-40 shrink-0 transition-all duration-300 relative"
    >
      <div
        class="h-16 flex items-center border-b border-[#363e42]/5 bg-white z-50 transition-all duration-300"
        :class="isSidebarOpen ? 'px-5' : 'justify-center px-0'"
      >
        <div class="w-8 h-8 bg-gradient-to-br from-[#363e42] to-[#1a1c1d] text-white rounded-[10px] flex items-center justify-center shadow-sm shrink-0">
          <span class="text-xs font-bold text-[#d97706]">HC</span>
        </div>
        <div
          class="flex flex-col whitespace-nowrap ml-3 transition-opacity duration-300"
          :class="isSidebarOpen ? 'opacity-100' : 'opacity-0 w-0 hidden'"
        >
          <h1 class="text-[14px] font-black tracking-tight text-[#363e42] leading-none">HaiCi 智能客服</h1>
        </div>
      </div>

      <div class="py-5 flex-1 bg-[#fcfcfc] overflow-y-auto flex flex-col gap-2">
        <nav class="flex flex-col gap-2 px-3">
          <button
            class="w-full flex items-center py-3 rounded-xl transition-all duration-300 shadow-sm relative"
            :class="currentView === 'chat' ? 'bg-[#363e42] text-white' : 'bg-white border border-[#363e42]/5 text-[#363e42] hover:bg-[#363e42]/5'"
            @click="currentView = 'chat'"
          >
            <div class="flex justify-center items-center shrink-0" :class="isSidebarOpen ? 'ml-4' : 'w-full'">
              <i class="fas fa-headset" :class="currentView === 'chat' ? 'text-[#d97706]' : ''"></i>
            </div>
            <span
              class="text-[12px] font-bold tracking-wide whitespace-nowrap transition-all duration-300 overflow-hidden"
              :class="isSidebarOpen ? 'ml-3 opacity-100' : 'ml-0 opacity-0 w-0'"
            >智能对话</span>
          </button>
          <button
            class="w-full flex items-center py-3 rounded-xl transition-all duration-300 shadow-sm relative"
            :class="currentView === 'kb' ? 'bg-[#363e42] text-white' : 'bg-white border border-[#363e42]/5 text-[#363e42] hover:bg-[#363e42]/5'"
            @click="currentView = 'kb'"
          >
            <div class="flex justify-center items-center shrink-0" :class="isSidebarOpen ? 'ml-4' : 'w-full'">
              <i class="fas fa-book" :class="currentView === 'kb' ? 'text-[#d97706]' : ''"></i>
            </div>
            <span
              class="text-[12px] font-bold tracking-wide whitespace-nowrap transition-all duration-300 overflow-hidden"
              :class="isSidebarOpen ? 'ml-3 opacity-100' : 'ml-0 opacity-0 w-0'"
            >知识库</span>
          </button>
        </nav>
      </div>

      <div class="p-3 border-t border-[#363e42]/5 bg-[#fcfcfc] flex items-center justify-center shrink-0">
        <button
          class="w-8 h-8 flex items-center justify-center rounded-lg text-[#363e42]/40 hover:bg-[#363e42]/10 hover:text-[#d97706] transition-colors"
          @click="isSidebarOpen = !isSidebarOpen"
        >
          <i class="fas text-[12px] transition-transform duration-300" :class="isSidebarOpen ? 'fa-chevron-left' : 'fa-chevron-right'"></i>
        </button>
      </div>
    </aside>

    <main class="flex-1 flex flex-col h-full bg-[#fdf6e3]/30 relative z-0">
      <header class="h-16 border-b border-[#363e42]/5 bg-white/80 backdrop-blur-md flex items-center justify-between px-6 shrink-0 z-10">
        <span class="text-[14px] font-black text-[#363e42]">{{ currentView === 'chat' ? '智能客服会话' : '知识库管理' }}</span>
      </header>

      <transition name="fade" mode="out-in">
        <div v-if="currentView === 'chat'" class="flex-1 flex flex-col overflow-hidden w-full h-full">
          <div id="chatContainer" class="flex-1 overflow-y-auto p-4 md:p-6 flex flex-col gap-6 chat-scroll">
            <div v-if="messages.length === 0" class="h-full flex flex-col items-center justify-center text-[#363e42]/30 mt-[-5%]">
              <p class="font-black tracking-widest uppercase text-xs opacity-80 text-[#363e42]">智能客服 Agent 已就绪</p>
              <p class="text-[11px] font-medium mt-2 opacity-50 text-[#363e42]">基于 RAG 知识库问答，支持流式输出与引用溯源</p>
            </div>

            <div
              v-for="(msg, index) in messages"
              :key="index"
              class="flex w-full"
              :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
            >
              <div class="max-w-[85%] md:max-w-[75%] flex gap-3" :class="msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'">
                <div
                  class="p-4 rounded-2xl shadow-sm border border-[#363e42]/5 text-[13px] leading-[1.7] whitespace-pre-wrap font-medium break-words"
                  :class="msg.role === 'user' ? 'bg-[#d97706]/10 text-[#363e42] rounded-tr-sm' : 'bg-white text-[#363e42]/90 rounded-tl-sm'"
                >
                  {{ msg.content }}
                  <div v-if="msg.intent" class="mt-2 text-[10px] text-[#d97706] font-bold">意图: {{ msg.intent }}</div>
                  <div v-if="msg.citations && msg.citations.length" class="mt-2 text-[11px] text-[#363e42]/70">
                    <div class="font-bold mb-1">参考来源</div>
                    <div v-for="(c, ci) in msg.citations" :key="ci">· {{ c.document_name }}：{{ c.snippet }}</div>
                  </div>
                  <div v-if="msg.messageId" class="mt-2 flex gap-2">
                    <button class="text-xs text-green-600" @click="submitFeedback(msg.messageId!, 1)">👍</button>
                    <button class="text-xs text-red-500" @click="submitFeedback(msg.messageId!, 0)">👎</button>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="isWaiting" class="flex w-full justify-start">
              <div class="p-4 rounded-2xl rounded-tl-sm bg-white border border-[#363e42]/5 shadow-sm flex items-center h-[46px]">
                <div class="wave-loader">
                  <div class="wave-dot"></div>
                  <div class="wave-dot"></div>
                  <div class="wave-dot"></div>
                </div>
              </div>
            </div>
          </div>

          <div class="p-4 bg-white/80 backdrop-blur-md border-t border-[#363e42]/5 shrink-0 z-10 pb-6">
            <div class="max-w-4xl mx-auto flex flex-col relative bg-white border border-[#363e42]/30 rounded-2xl p-2 shadow-sm focus-within:border-[#d97706]/60 transition-all">
              <div class="flex items-end gap-2">
                <textarea
                  v-model="inputText"
                  rows="1"
                  class="flex-1 max-h-[140px] min-h-[40px] bg-transparent border-none focus:ring-0 resize-none text-[13px] text-[#363e42] py-2.5 px-2 chat-scroll"
                  placeholder="请输入您的问题..."
                  @keydown.enter.prevent.exact="sendMessage"
                  @input="adjustTextareaHeight"
                />
                <button
                  :class="isRecording ? 'text-white bg-[#d97706] recording-pulse' : 'text-[#363e42]/60 hover:text-[#d97706] hover:bg-[#d97706]/10'"
                  class="w-10 h-10 flex items-center justify-center shrink-0 rounded-xl transition-all"
                  title="语音输入"
                  @click="toggleRecording"
                >
                  <i class="fas fa-microphone text-[18px]"></i>
                </button>
                <button
                  :disabled="!inputText.trim() || isWaiting"
                  class="w-10 h-10 flex items-center justify-center shrink-0 bg-[#363e42] text-white rounded-xl hover:bg-[#22272a] disabled:bg-[#363e42]/20 transition-colors shadow-sm active:scale-95"
                  @click="sendMessage"
                >
                  <i class="fas fa-paper-plane text-[13px] ml-[-2px] mt-[2px]"></i>
                </button>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="flex-1 flex flex-col p-6 overflow-y-auto">
          <div class="max-w-5xl mx-auto w-full">
            <div class="flex items-center justify-between mb-6">
              <h2 class="text-lg font-black text-[#363e42]">知识库管理</h2>
              <label class="bg-[#363e42] text-white px-5 py-2.5 rounded-xl font-bold text-[13px] cursor-pointer">
                上传文档 (.txt/.md/.pdf)
                <input type="file" class="hidden" accept=".txt,.md,.pdf" @change="uploadKnowledge" />
              </label>
            </div>
            <div class="bg-white rounded-2xl border border-[#363e42]/5 overflow-hidden">
              <table class="w-full text-sm">
                <thead class="bg-[#fcfcfc] text-[#363e42]/60">
                  <tr>
                    <th class="p-3 text-left">文档</th>
                    <th class="p-3 text-left">状态</th>
                    <th class="p-3 text-left">分块</th>
                    <th class="p-3 text-left">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="d in kbDocs" :key="d.id" class="border-t border-[#363e42]/5">
                    <td class="p-3">{{ d.filename }}</td>
                    <td class="p-3">{{ d.status }}</td>
                    <td class="p-3">{{ d.chunk_count }}</td>
                    <td class="p-3">
                      <button class="text-red-500" @click="deleteKnowledge(d.id)">删除</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </transition>
    </main>
  </div>
</template>
