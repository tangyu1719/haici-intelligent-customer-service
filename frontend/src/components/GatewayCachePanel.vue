<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface CacheStats { exact_hits:number; semantic_hits:number; misses:number; hit_rate:number; entries:number; max_entries:number }
const stats = ref<CacheStats>({exact_hits:0,semantic_hits:0,misses:0,hit_rate:0,entries:0,max_entries:1000})
const exactEnabled = ref(true)
const semanticEnabled = ref(true)
const ttlSeconds = ref(300)
const similarityThreshold = ref(0.92)
const msg = ref('')

async function loadStats() {
  try {
    const r = await fetch('/api/v1/settings/cache/stats', { headers: authHeaders() })
    if (r.ok) stats.value = (await r.json()).stats
  } catch {}
}
async function clearCache() {
  if (!confirm('确定清除所有缓存？')) return
  const r = await fetch('/api/v1/settings/cache/invalidate', { method:'POST', headers:authHeaders() })
  if (r.ok) { msg.value = '缓存已清除'; await loadStats() }
}
onMounted(()=>loadStats())
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-3xl mx-auto">
      <h2 class="text-lg font-black mb-1">缓存管理</h2>
      <p class="text-[11px] text-[#64748b] mb-4">精确匹配(TTL去重) + 语义匹配(向量相似度)，减少重复LLM调用。</p>
      <p v-if="msg" class="text-[12px] text-green-600 mb-3">{{ msg }}</p>

      <!-- 统计卡片 -->
      <div class="grid grid-cols-4 gap-3 mb-4">
        <div class="bg-white border rounded-xl p-3 text-center">
          <div class="text-[24px] font-black" :class="stats.hit_rate>0.5?'text-green-500':'text-[#64748b]'">{{ (stats.hit_rate*100).toFixed(0) }}%</div>
          <div class="text-[10px] text-[#94a3b8]">命中率</div>
        </div>
        <div class="bg-white border rounded-xl p-3 text-center">
          <div class="text-[24px] font-black text-[#2563eb]">{{ stats.exact_hits }}</div>
          <div class="text-[10px] text-[#94a3b8]">精确命中</div>
        </div>
        <div class="bg-white border rounded-xl p-3 text-center">
          <div class="text-[24px] font-black text-purple-500">{{ stats.semantic_hits }}</div>
          <div class="text-[10px] text-[#94a3b8]">语义命中</div>
        </div>
        <div class="bg-white border rounded-xl p-3 text-center">
          <div class="text-[24px] font-black text-red-400">{{ stats.misses }}</div>
          <div class="text-[10px] text-[#94a3b8]">未命中</div>
        </div>
      </div>

      <!-- 配置 -->
      <div class="bg-white border rounded-xl p-4 mb-4 space-y-4">
        <h3 class="text-[14px] font-bold">缓存配置</h3>
        <div class="grid grid-cols-2 gap-4 text-[12px]">
          <label class="flex items-center gap-2 cursor-pointer">
            <input v-model="exactEnabled" type="checkbox" /> 精确匹配(TTL去重)
            <span class="text-[10px] text-[#94a3b8]">相同问题Hash匹配</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input v-model="semanticEnabled" type="checkbox" /> 语义匹配
            <span class="text-[10px] text-[#94a3b8]">向量相似度匹配</span>
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-[11px] text-[#64748b] font-bold">TTL (秒)</span>
            <input v-model.number="ttlSeconds" type="number" class="border rounded-lg px-3 py-1.5" min="30" max="3600" />
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-[11px] text-[#64748b] font-bold">语义相似度阈值</span>
            <input v-model.number="similarityThreshold" type="number" class="border rounded-lg px-3 py-1.5" min="0.7" max="1" step="0.01" />
          </label>
        </div>
        <div class="flex items-center gap-3 text-[11px] text-[#94a3b8]">
          <span>缓存条目: {{ stats.entries }} / {{ stats.max_entries }}</span>
          <div class="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div class="h-full bg-blue-400 rounded-full" :style="{width:(stats.entries/stats.max_entries*100)+'%'}"></div>
          </div>
        </div>
      </div>

      <div class="flex gap-3">
        <button class="bg-[#2563eb] text-white px-5 py-2 rounded-lg font-bold text-[12px]" @click="loadStats">刷新统计</button>
        <button class="border border-red-300 text-red-500 px-5 py-2 rounded-lg font-bold text-[12px]" @click="clearCache">清除缓存</button>
      </div>
    </div>
  </div>
</template>
