<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface PipelineConfig { ok: boolean; ollama_available: boolean; ollama_base_url: string; ollama_model: string; models: {key:string;label:string;env_model:string}[] }
const config = ref<PipelineConfig|null>(null)
const intentModel = ref('local_05b')
const msg = ref('')

async function load() {
  const r = await fetch('/api/v1/settings/pipeline-config', { headers: authHeaders() })
  if (r.ok) {
    config.value = await r.json()
    // 推断当前选中
    if (!config.value?.ollama_model) intentModel.value = 'api_gateway'
    else if (config.value?.ollama_model?.includes('1.5')) intentModel.value = 'local_15b'
    else intentModel.value = 'local_05b'
  }
}
async function save() {
  msg.value = ''
  const r = await fetch('/api/v1/settings/pipeline-config', {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ intent_model: intentModel.value }),
  })
  msg.value = r.ok ? '已保存，需重启后端生效' : '保存失败'
}

onMounted(load)
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-2xl mx-auto">
      <h2 class="text-lg font-black mb-1">管道设置</h2>
      <p class="text-[11px] text-[#64748b] mb-4">配置 RAG 管道中意图识别与 Query 改写使用的模型</p>
      <p v-if="msg" class="text-[12px] mb-3 font-bold" :class="msg.includes('失败')?'text-red-500':'text-green-600'">{{ msg }}</p>

      <div class="bg-white border rounded-xl p-4 space-y-4">
        <h3 class="text-[13px] font-bold">意图识别 / Query 改写模型</h3>
        <p class="text-[11px] text-[#64748b]">
          该模型负责将用户口语问题改写为检索友好格式（意图分类 + 关键词提取 + 检索词映射）。
          默认使用本地 Ollama 模型（速度 1-2s），未安装时自动回退到 API 网关。
        </p>

        <div class="space-y-2">
          <label v-for="m in config?.models" :key="m.key" class="flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors"
            :class="intentModel===m.key?'border-[#2563eb] bg-[#eff6ff]':'border-[#e2e8f0] hover:bg-[#f8fafc]'">
            <input v-model="intentModel" type="radio" :value="m.key" class="mt-0.5" />
            <div>
              <div class="text-[12px] font-bold">{{ m.label }}</div>
              <div class="text-[10px] text-[#94a3b8] mt-0.5">
                <span v-if="m.key==='local_05b'">🚀 CPU即跑，改写延迟 ~1s，适合开发测试</span>
                <span v-else-if="m.key==='local_15b'">⚡ 更准确的理解能力，改写延迟 ~2s</span>
                <span v-else>☁️ 使用 ARK 豆包等云端模型，延迟 ~10s，质量最高</span>
              </div>
            </div>
          </label>
        </div>

        <div v-if="config&&!config.ollama_available" class="text-[11px] p-3 bg-amber-50 border border-amber-200 rounded-lg">
          ⚠️ 未检测到 Ollama 运行。请先安装 <a href="https://ollama.com/download/windows" class="text-[#2563eb] underline" target="_blank">Ollama</a>，
          然后执行 <code class="bg-amber-100 px-1 rounded">ollama pull qwen2:0.5b</code> 和 <code class="bg-amber-100 px-1 rounded">ollama pull qwen2:1.5b</code>
        </div>

        <button class="bg-[#2563eb] text-white px-5 py-2 rounded-lg font-bold text-[12px] disabled:opacity-50" @click="save">
          保存配置
        </button>
      </div>
    </div>
  </div>
</template>
