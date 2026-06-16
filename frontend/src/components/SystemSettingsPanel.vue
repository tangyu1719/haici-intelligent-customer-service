<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

type CeilingMode = 'smart' | 'hard'

const intervalMinutes = ref(10)
const ceilingMode = ref<CeilingMode>('smart')
const ceilingMap = ref('100:10,50:5,20:3')
const loading = ref(false)
const saving = ref(false)
const msg = ref('')

const mapPreview = computed(() => {
  const parts = ceilingMap.value.split(',').map((s) => s.trim()).filter(Boolean)
  if (!parts.length) return '格式：粗筛池下限:精筛上限，如 100:10,50:5,20:3'
  return parts.map((p) => {
    const [pool, k] = p.split(':')
    return `粗筛 ≥ ${pool} 条 → 最多留 ${k} 条`
  }).join('；')
})

const loadSettings = async (): Promise<void> => {
  loading.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/v1/admin/system/settings', { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      intervalMinutes.value = data.session_active_persist_interval_minutes ?? 10
      ceilingMode.value = data.rag_pool_ceiling_mode === 'hard' ? 'hard' : 'smart'
      ceilingMap.value = data.rag_pool_ceiling_map || '100:10,50:5,20:3'
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
      body: JSON.stringify({
        session_active_persist_interval_minutes: intervalMinutes.value,
        rag_pool_ceiling_mode: ceilingMode.value,
        rag_pool_ceiling_map: ceilingMap.value,
      }),
    })
    if (res.ok) {
      const data = await res.json()
      ceilingMode.value = data.rag_pool_ceiling_mode === 'hard' ? 'hard' : 'smart'
      ceilingMap.value = data.rag_pool_ceiling_map || ceilingMap.value
      msg.value = '已保存'
    } else {
      msg.value = '保存失败'
    }
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <div :class="embedded ? '' : 'flex-1 p-6 overflow-y-auto'">
    <div class="bg-white border rounded-2xl p-6 space-y-5" :class="embedded ? 'max-w-2xl' : 'max-w-2xl mx-auto'">
      <div v-if="!embedded">
        <h2 class="text-lg font-black">系统设置</h2>
        <p class="text-[11px] text-[#64748b] mt-1">全局运行参数，修改后即时生效</p>
      </div>

      <div v-if="loading" class="text-[12px] text-[#64748b]">加载中…</div>
      <template v-else>
        <div class="border rounded-xl p-4 space-y-2">
          <label class="text-[12px] font-bold text-[#363e42]">活跃会话落库间隔（分钟）</label>
          <p class="text-[11px] text-[#64748b] leading-relaxed">
            用户正在「智能对话」中打开的会话，将按此间隔自动落库到 MySQL，供「会话历史」查询。
            切换/退出会话时会立即落库。
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

        <div class="border rounded-xl p-4 space-y-3">
          <label class="text-[12px] font-bold text-[#363e42]">RAG 精筛落档策略</label>
          <p class="text-[11px] text-[#64748b] leading-relaxed">
            粗筛大池经 BM25+向量精筛后，按粗筛池大小与分数质量决定最终保留条数。
            可选择「智能梯度」或「硬配置映射表」两种方式。
          </p>

          <div class="flex flex-wrap gap-4 mt-1">
            <label class="flex items-center gap-2 text-[12px] cursor-pointer">
              <input v-model="ceilingMode" type="radio" value="smart" />
              <span>智能梯度（推荐）</span>
            </label>
            <label class="flex items-center gap-2 text-[12px] cursor-pointer">
              <input v-model="ceilingMode" type="radio" value="hard" />
              <span>硬配置映射</span>
            </label>
          </div>

          <p v-if="ceilingMode === 'smart'" class="text-[11px] text-[#475569] bg-slate-50 rounded-lg p-3 leading-relaxed">
            按粗筛池占 <code class="text-[10px]">RAG_COARSE_POOL_K</code> 的比例自动映射到梯度档位
            （默认 10/8/5/3），并结合精筛分数质量（高/中/低）与分数断层动态落档。
          </p>

          <template v-else>
            <label class="text-[11px] font-bold text-[#363e42]">映射表</label>
            <input
              v-model="ceilingMap"
              type="text"
              class="border rounded-lg px-3 py-2 text-sm w-full font-mono"
              placeholder="100:10,50:5,20:3"
            />
            <p class="text-[11px] text-[#64748b]">{{ mapPreview }}</p>
          </template>
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
