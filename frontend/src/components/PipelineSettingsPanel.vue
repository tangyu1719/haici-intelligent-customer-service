<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface PipelineConfig { ok: boolean; ollama_available: boolean; ollama_base_url: string; ollama_model: string; models: {key:string;label:string;env_model:string}[] }
interface OllamaModel { name: string; size: string }
const config = ref<PipelineConfig|null>(null)
const intentModel = ref('api_gateway')
const msg = ref('')
const ollamaStatus = ref<'idle'|'testing'|'connected'|'disconnected'>('idle')
const ollamaModels = ref<OllamaModel[]>([])
const gatewayModel = ref('')
const testBusy = ref(false)

async function load() {
  const r = await fetch('/api/v1/settings/pipeline-config', { headers: authHeaders() })
  if (r.ok) {
    config.value = await r.json()
    if (!config.value?.ollama_model) intentModel.value = 'api_gateway'
    else if (config.value?.ollama_model?.includes('1.5')) intentModel.value = 'local_15b'
    else intentModel.value = 'local_05b'
    if (config.value?.ollama_available) testConnection()
  }
  // 获取网关当前模型
  try {
    const gr = await fetch('/api/v1/settings/gateway-snapshot', { headers: authHeaders() })
    if (gr.ok) {
      const gd = await gr.json()
      const qa = gd.task_type_route?.qa
      if (qa) gatewayModel.value = `${qa.provider} / ${qa.model}`
    }
  } catch {}
}

async function testConnection() {
  testBusy.value = true; ollamaStatus.value = 'testing'
  try {
    const base = config.value?.ollama_base_url || 'http://127.0.0.1:11434/v1'
    const r = await fetch(`${base.replace('/v1','')}/api/tags`)
    if (r.ok) {
      ollamaStatus.value = 'connected'
      const data = await r.json()
      ollamaModels.value = (data.models || []).map((m: any) => ({
        name: m.name, size: m.size ? (m.size / 1e9).toFixed(1) + 'GB' : '?'
      }))
    } else {
      ollamaStatus.value = 'disconnected'
    }
  } catch {
    ollamaStatus.value = 'disconnected'
  } finally { testBusy.value = false }
}

async function save() {
  msg.value = ''
  const r = await fetch('/api/v1/settings/pipeline-config', {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ intent_model: intentModel.value }),
  })
  msg.value = r.ok ? '配置已保存' : '保存失败'
}

onMounted(load)
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-2xl mx-auto">
      <h2 class="text-lg font-black mb-1">管道设置</h2>
      <p class="text-[11px] text-[#64748b] mb-4">意图识别+Query改写模型选择 · 未选时走网关路由</p>
      <p v-if="msg" class="text-[12px] mb-3 font-bold" :class="msg.includes('失败')?'text-red-500':'text-green-600'">{{ msg }}</p>

      <!-- 连接状态卡片 -->
      <div class="grid grid-cols-2 gap-3 mb-4">
        <div class="bg-white border rounded-xl p-3 flex items-center gap-3">
          <div class="w-10 h-10 rounded-full flex items-center justify-center text-lg"
            :class="ollamaStatus==='connected'?'bg-green-100':'bg-gray-100'">
            {{ ollamaStatus==='connected'?'🟢':ollamaStatus==='testing'?'⏳':'🔴' }}
          </div>
          <div>
            <div class="text-[11px] font-bold">Ollama 本地</div>
            <div class="text-[10px]" :class="ollamaStatus==='connected'?'text-green-600':'text-red-400'">
              {{ ollamaStatus==='connected'?'已连接':ollamaStatus==='testing'?'检测中...':'未连接' }}
            </div>
            <div v-if="ollamaModels.length" class="text-[9px] text-[#94a3b8]">{{ ollamaModels.map(m=>m.name).join(', ') }}</div>
          </div>
          <button class="ml-auto text-[10px] border px-2 py-0.5 rounded" :disabled="testBusy" @click="testConnection">
            {{ testBusy?'检测中':'重测' }}
          </button>
        </div>
        <div class="bg-white border rounded-xl p-3 flex items-center gap-3">
          <div class="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-lg">☁️</div>
          <div>
            <div class="text-[11px] font-bold">网关模型</div>
            <div class="text-[10px] text-[#64748b]">{{ gatewayModel || '未配置' }} (自动路由)</div>
          </div>
        </div>
      </div>

      <!-- 管道流程说明 -->
      <div class="bg-white border rounded-xl p-3 mb-4">
        <div class="text-[11px] font-bold mb-2">管道路由流程</div>
        <div class="flex items-center gap-1 text-[10px] text-[#64748b] flex-wrap">
          <span class="bg-blue-100 px-1.5 py-0.5 rounded">{{ intentModel.startsWith('local')?'Ollama '+config?.ollama_model:'API 网关' }}</span>
          <span>→</span>
          <span class="bg-green-100 px-1.5 py-0.5 rounded">意图识别</span>
          <span>→</span>
          <span class="bg-green-100 px-1.5 py-0.5 rounded">Query改写</span>
          <span>→</span>
          <span class="bg-purple-100 px-1.5 py-0.5 rounded">RAG检索</span>
          <span>→</span>
          <span class="bg-amber-100 px-1.5 py-0.5 rounded">LLM生成</span>
          <span class="text-[9px] text-[#94a3b8] ml-1">(始终走网关)</span>
        </div>
      </div>

      <!-- 模型选择 -->
      <div class="bg-white border rounded-xl p-4">
        <h3 class="text-[13px] font-bold mb-3">意图识别 / Query 改写模型</h3>

        <div class="space-y-2">
          <label v-for="m in config?.models" :key="m.key" class="flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors"
            :class="intentModel===m.key?'border-[#2563eb] bg-[#eff6ff]':'border-[#e2e8f0] hover:bg-[#f8fafc]'">
            <input v-model="intentModel" type="radio" :value="m.key" class="mt-0.5" />
            <div class="flex-1">
              <div class="flex items-center gap-2">
                <span class="text-[12px] font-bold">{{ m.label }}</span>
                <span v-if="m.key==='api_gateway'&&ollamaStatus!=='connected'" class="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-600">当前使用</span>
                <span v-if="m.key!=='api_gateway'&&ollamaStatus!=='connected'" class="text-[9px] px-1.5 py-0.5 rounded-full bg-red-100 text-red-400">需Ollama</span>
                <span v-if="m.key!=='api_gateway'&&ollamaModels.some(om=>m.env_model&&om.name.includes(m.env_model.replace(':','')));" class="text-[9px] px-1.5 py-0.5 rounded-full bg-green-100 text-green-600">已安装</span>
              </div>
              <div class="text-[10px] text-[#94a3b8] mt-0.5">
                <span v-if="m.key==='local_05b'">🚀 本地CPU推理，改写 ~1s，磁盘 ~400MB</span>
                <span v-else-if="m.key==='local_15b'">⚡ 更强的语义理解，改写 ~2s，磁盘 ~1GB</span>
                <span v-else>☁️ 通过网关路由调用 ARK/豆包，延迟 ~10s，质量最高</span>
              </div>
            </div>
          </label>
        </div>

        <div v-if="ollamaStatus==='disconnected'" class="text-[11px] p-3 mt-3 bg-amber-50 border border-amber-200 rounded-lg">
          ⚠️ Ollama 未连接。请先安装 <a href="https://ollama.com/download/windows" class="text-[#2563eb] underline" target="_blank">Ollama</a>，
          然后执行 <code class="bg-amber-100 px-1 rounded">ollama pull qwen2:0.5b</code> 和 <code class="bg-amber-100 px-1 rounded">ollama pull qwen2:1.5b</code>，
          点击上方「重测」按钮刷新状态。
        </div>

        <button class="bg-[#2563eb] text-white px-5 py-2 rounded-lg font-bold text-[12px] disabled:opacity-50 mt-4" @click="save">
          保存配置
        </button>
      </div>
    </div>
  </div>
</template>
