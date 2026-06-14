<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { setAuth } from '../api/auth'

const router = useRouter()
const route = useRoute()

type Mode = 'login' | 'register' | 'sms'

const mode = ref<Mode>('login')
const identifier = ref('')
const password = ref('')
const smsPhone = ref('')
const smsCode = ref('')
const email = ref('')
const regPassword = ref('')
const regCode = ref('')
const nickname = ref('')
const username = ref('')
const loading = ref(false)
const msg = ref('')

const sendCode = async (target: string, codeType: string, purpose: string): Promise<void> => {
  const res = await fetch('/api/v1/auth/send-code', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, code_type: codeType, purpose }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '发送失败')
  msg.value = data.message || '验证码已发送（开发环境见后端日志）'
}

const doPasswordLogin = async (): Promise<void> => {
  loading.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        login_type: 'password',
        identifier: identifier.value.trim(),
        credential: password.value,
      }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '登录失败')
    setAuth(data.access_token, data.refresh_token, data.user)
    await router.replace((route.query.redirect as string) || '/chat')
  } catch (e) {
    msg.value = e instanceof Error ? e.message : '登录失败'
  } finally {
    loading.value = false
  }
}

const doSmsLogin = async (): Promise<void> => {
  loading.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        login_type: 'sms',
        identifier: smsPhone.value.trim(),
        credential: smsCode.value.trim(),
      }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '登录失败')
    setAuth(data.access_token, data.refresh_token, data.user)
    if (data.is_new_user) msg.value = '已为您创建账号'
    await router.replace((route.query.redirect as string) || '/chat')
  } catch (e) {
    msg.value = e instanceof Error ? e.message : '登录失败'
  } finally {
    loading.value = false
  }
}

const doRegister = async (): Promise<void> => {
  if (!email.value.trim()) {
    msg.value = '邮箱为必填项'
    return
  }
  loading.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.value.trim(),
        password: regPassword.value,
        code: regCode.value.trim(),
        nickname: nickname.value.trim() || undefined,
        username: username.value.trim() || undefined,
      }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '注册失败')
    setAuth(data.access_token, data.refresh_token, data.user)
    await router.replace('/chat')
  } catch (e) {
    msg.value = e instanceof Error ? e.message : '注册失败'
  } finally {
    loading.value = false
  }
}

const onSendSmsCode = async (): Promise<void> => {
  try {
    await sendCode(smsPhone.value.trim(), 'sms', 'login')
  } catch (e) {
    msg.value = e instanceof Error ? e.message : '发送失败'
  }
}

const onSendRegisterCode = async (): Promise<void> => {
  try {
    await sendCode(email.value.trim(), 'email', 'register')
  } catch (e) {
    msg.value = e instanceof Error ? e.message : '发送失败'
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-[#fdf6e3]/40 p-4">
    <div class="bg-white rounded-2xl p-8 w-full max-w-md shadow-xl border border-[#363e42]/5">
      <div class="flex items-center gap-3 mb-6">
        <div class="w-10 h-10 bg-gradient-to-br from-[#363e42] to-[#1a1c1d] text-white rounded-xl flex items-center justify-center">
          <span class="text-sm font-bold text-[#d97706]">HC</span>
        </div>
        <div>
          <h1 class="text-lg font-black text-[#363e42]">HaiCi 智能客服</h1>
          <p class="text-xs text-[#363e42]/50">手机号 / 邮箱 / 用户名 + 密码登录</p>
        </div>
      </div>

      <!-- 密码登录（默认） -->
      <template v-if="mode === 'login'">
        <input v-model="identifier" class="w-full border rounded-lg p-2.5 mb-2 text-sm" placeholder="手机号 / 邮箱 / 用户名" />
        <input v-model="password" type="password" class="w-full border rounded-lg p-2.5 mb-4 text-sm" placeholder="密码" @keydown.enter="doPasswordLogin" />
        <button class="w-full bg-[#363e42] text-white py-2.5 rounded-lg font-bold mb-3" :disabled="loading" @click="doPasswordLogin">
          {{ loading ? '登录中...' : '登录' }}
        </button>
        <p class="text-[11px] text-[#363e42]/50 text-center mb-3">
          首次使用？
          <button type="button" class="text-[#d97706] font-bold" @click="mode = 'sms'">手机号验证码免注册登录</button>
        </p>
        <button type="button" class="w-full border border-[#d97706] text-[#d97706] py-2.5 rounded-lg font-bold text-sm" @click="mode = 'register'">
          注册账号
        </button>
      </template>

      <!-- 短信免注册 -->
      <template v-else-if="mode === 'sms'">
        <p class="text-xs text-[#363e42]/60 mb-3">未注册手机号验证通过后将自动开户，昵称默认「小鱼儿_用户号」</p>
        <input v-model="smsPhone" class="w-full border rounded-lg p-2.5 mb-2 text-sm" placeholder="手机号" />
        <div class="flex gap-2 mb-4">
          <input v-model="smsCode" class="flex-1 border rounded-lg p-2.5 text-sm" placeholder="短信验证码" />
          <button class="px-3 rounded-lg bg-[#363e42]/10 text-xs font-bold shrink-0" @click="onSendSmsCode">获取验证码</button>
        </div>
        <button class="w-full bg-[#363e42] text-white py-2.5 rounded-lg font-bold mb-2" :disabled="loading" @click="doSmsLogin">
          {{ loading ? '登录中...' : '验证码登录' }}
        </button>
        <button type="button" class="w-full text-xs text-[#363e42]/50 py-2" @click="mode = 'login'">← 返回密码登录</button>
      </template>

      <!-- 注册（邮箱必填） -->
      <template v-else>
        <p class="text-xs text-[#d97706] font-bold mb-3">注册 · 邮箱必填</p>
        <input v-model="email" class="w-full border rounded-lg p-2.5 mb-2 text-sm" placeholder="邮箱 *" required />
        <div class="flex gap-2 mb-2">
          <input v-model="regCode" class="flex-1 border rounded-lg p-2.5 text-sm" placeholder="邮箱验证码 *" />
          <button class="px-3 rounded-lg bg-[#363e42]/10 text-xs font-bold shrink-0" @click="onSendRegisterCode">获取验证码</button>
        </div>
        <input v-model="regPassword" type="password" class="w-full border rounded-lg p-2.5 mb-2 text-sm" placeholder="密码（至少6位）*" />
        <input v-model="nickname" class="w-full border rounded-lg p-2.5 mb-2 text-sm" placeholder="昵称（可选）" />
        <input v-model="username" class="w-full border rounded-lg p-2.5 mb-4 text-sm" placeholder="用户名（可选）" />
        <button class="w-full bg-[#d97706] text-white py-2.5 rounded-lg font-bold mb-2" :disabled="loading" @click="doRegister">
          {{ loading ? '注册中...' : '注册并登录' }}
        </button>
        <button type="button" class="w-full text-xs text-[#363e42]/50 py-2" @click="mode = 'login'">已有账号？返回登录</button>
      </template>

      <p v-if="msg" class="text-xs mt-3 text-center" :class="msg.includes('失败') || msg.includes('错误') ? 'text-red-500' : 'text-[#363e42]/70'">{{ msg }}</p>
    </div>
  </div>
</template>
