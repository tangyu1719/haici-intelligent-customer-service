<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

const intervalMinutes = ref(10)
const loading = ref(false)
const saving = ref(false)
const msg = ref('')

const loadSettings = async (): Promise<void> => {
  loading.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/v1/admin/system/settings', { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      intervalMinutes.value = data.session_active_persist_interval_minutes ?? 10
    } else {
      msg.value = '加载设置失败'
    }
  } finally {
    loading.value = false
  }
}

const saveSettings = async (): Promise<void> => {
  saving.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/v1/admin/system/settings', {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify({ session_active_persist_interval_minutes: intervalMinutes.value }),
    })
    msg.value = res.ok ? '已保存' : '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-xl mx-auto bg-white border rounded-2xl p-6 space-y-5">
      <div>
        <h2 class="text-lg font-black">系统设置</h2>
        <p class="text-[11px] text-[#64748b] mt-1">全局运行参数，修改后即时生效</p>
      </div>

      <div v-if="loading" class="text-[12px] text-[#64748b]">加载中…</div>
      <template v-else>
        <div class="border rounded-xl p-4 space-y-2">
          <label class="text-[12px] font-bold text-[#363e42]">活跃会话落库间隔（分钟）</label>
          <p class="text-[11px] text-[#64748b] leading-relaxed">
            用户正在「智能对话」中打开的会话，将按此间隔自动落库到 MySQL，供「会话历史」查询。
            切换/退出会话时会立即落库。消息在对话过程中也会逐条异步写入，此处主要刷新会话元数据与时间戳。
          </p>
          <div class="flex items-center gap-3 mt-2">
            <input
              v-model.number="intervalMinutes"
              type="number"
              min="1"
              max="120"
              class="border rounded-lg px-3 py-2 text-sm w-24"
            />
            <span class="text-[11px] text-[#64748b]">分钟（1–120）</span>
          </div>
        </div>

        <div class="flex items-center gap-3">
          <button
            type="button"
            class="bg-[#2563eb] text-white px-5 py-2 rounded-lg text-[12px] font-bold disabled:opacity-50"
            :disabled="saving"
            @click="saveSettings"
          >
            {{ saving ? '保存中…' : '保存设置' }}
          </button>
          <span v-if="msg" class="text-[12px] font-bold" :class="msg.includes('失败') ? 'text-red-500' : 'text-green-600'">{{ msg }}</span>
        </div>
      </template>
    </div>
  </div>
</template>
