<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

const markdown = ref('')
const loading = ref(false)
const saving = ref(false)
const msg = ref('')

const loadProfile = async (): Promise<void> => {
  loading.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/v1/user-profiles/me', { headers: authHeaders() })
    if (!res.ok) {
      msg.value = '加载画像失败'
      return
    }
    const data = await res.json()
    markdown.value = data.markdown || ''
  } finally {
    loading.value = false
  }
}

const saveProfile = async (): Promise<void> => {
  saving.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/v1/user-profiles/me', {
      method: 'PUT',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ markdown: markdown.value }),
    })
    const data = await res.json()
    if (!res.ok) {
      msg.value = typeof data.detail === 'string' ? data.detail : '保存失败'
      return
    }
    markdown.value = data.markdown || ''
    msg.value = '保存成功'
  } finally {
    saving.value = false
  }
}

onMounted(loadProfile)
</script>

<template>
  <div class="space-y-4 max-w-3xl mx-auto">
    <header>
      <h2 class="text-lg font-bold text-[#363e42]">我的画像</h2>
      <p class="text-xs text-[#363e42]/50 mt-1">
        此处为 AI 长期记忆用的 Markdown 画像，仅您本人可编辑；5 星反馈与会话归档也会自动沉淀。
      </p>
    </header>

    <p v-if="loading" class="text-sm text-[#363e42]/40">加载中…</p>
    <template v-else>
      <textarea
        v-model="markdown"
        class="w-full min-h-[420px] border rounded-xl p-4 text-sm font-mono leading-relaxed resize-y"
        placeholder="在此编辑您的 Markdown 画像…"
      />
      <div class="flex items-center justify-between gap-3">
        <p v-if="msg" class="text-xs" :class="msg === '保存成功' ? 'text-green-600' : 'text-[#d97706]'">{{ msg }}</p>
        <span v-else class="text-xs text-[#363e42]/40">{{ markdown.length }} 字</span>
        <button
          type="button"
          class="px-5 py-2 rounded-lg bg-[#363e42] text-white text-sm font-bold disabled:opacity-50"
          :disabled="saving"
          @click="saveProfile"
        >
          {{ saving ? '保存中…' : '保存画像' }}
        </button>
      </div>
    </template>
  </div>
</template>
