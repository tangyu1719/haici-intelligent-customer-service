<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { authHeaders } from '../api/auth'

interface GatewayNode {
  id: string; name: string; provider: string
  base_url: string; api_key: string; endpoint_id: string
  model: string; priority: number; weight: number
  status: string; tags: string[]
}
interface TestResult { provider: string; model: string; ok: boolean; status_code?: number; latency_ms?: number; error?: string }
interface ProviderDef { key: string; label: string; defaultBaseUrl: string; defaultModel: string; needsEndpoint: boolean; endpointLabel: string; endpointHint: string }

// ═══ 常量定义（最前，避免 TDZ） ═══
const PROVIDERS: ProviderDef[] = [
  { key: 'ark', label: '火山方舟 ARK', defaultBaseUrl: 'https://ark.cn-beijing.volces.com/api/v3', defaultModel: 'ep-20260418230009-b9grz', needsEndpoint: true, endpointLabel: 'Endpoint ID', endpointHint: '推理端点ID，如 ep-2026xxxxxxxx-xxxxx' },
  { key: 'claude', label: 'Anthropic Claude', defaultBaseUrl: 'https://api.anthropic.com', defaultModel: 'claude-sonnet-4-6', needsEndpoint: false, endpointLabel: '', endpointHint: '' },
  { key: 'qwen', label: '通义千问 DashScope', defaultBaseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', defaultModel: 'qwen-turbo', needsEndpoint: false, endpointLabel: '', endpointHint: '' },
  { key: 'openai', label: 'OpenAI', defaultBaseUrl: 'https://api.openai.com/v1', defaultModel: 'gpt-4o', needsEndpoint: false, endpointLabel: '', endpointHint: '' },
]

function emptyNode(): GatewayNode {
  return {
    id: 'node_' + Date.now(), name: '', provider: 'ark',
    base_url: PROVIDERS[0].defaultBaseUrl, api_key: '', endpoint_id: '',
    model: PROVIDERS[0].defaultModel, priority: 10, weight: 100,
    status: 'active', tags: [],
  }
}

// ═══ 响应式状态 ═══
const nodes = ref<GatewayNode[]>([])
const showForm = ref(false)
const editingNode = ref<GatewayNode>(emptyNode())
const testResult = ref<TestResult | null>(null)
const testBusy = ref(false)
const saveMsg = ref('')
const selectedProvider = ref<ProviderDef>(PROVIDERS[0])

const providerLabel = (p: string) => PROVIDERS.find(x => x.key === p)?.label || p
const statusLabel = (s: string) => ({ active: '启用', disabled: '禁用', degraded: '降级' } as Record<string,string>)[s] || s

watch(() => editingNode.value?.provider, (prov) => {
  const def = PROVIDERS.find(p => p.key === prov)
  if (!def || !editingNode.value) return
  selectedProvider.value = def
  if (!editingNode.value.base_url || editingNode.value.base_url === PROVIDERS.find(p => p.key !== prov)?.defaultBaseUrl) editingNode.value.base_url = def.defaultBaseUrl
  if (!editingNode.value.model || editingNode.value.model === PROVIDERS.find(p => p.key !== prov)?.defaultModel) editingNode.value.model = def.defaultModel
})

// ═══ API ═══
async function loadNodes() {
  const r = await fetch('/api/v1/settings/gateway-nodes', { headers: authHeaders() })
  if (r.ok) nodes.value = (await r.json()).nodes || []
}
function startAdd() { editingNode.value = emptyNode(); selectedProvider.value = PROVIDERS[0]; showForm.value = true; testResult.value = null; saveMsg.value = '' }
function startEdit(n: GatewayNode) { editingNode.value = { ...n, tags: [...n.tags] }; selectedProvider.value = PROVIDERS.find(p => p.key === n.provider) || PROVIDERS[0]; showForm.value = true; testResult.value = null; saveMsg.value = '' }
function cancelEdit() { showForm.value = false; testResult.value = null; saveMsg.value = '' }
async function saveNode() {
  if (!editingNode.value) return
  editingNode.value.provider = selectedProvider.value.key
  if (!editingNode.value.base_url) editingNode.value.base_url = selectedProvider.value.defaultBaseUrl
  if (!editingNode.value.model) editingNode.value.model = selectedProvider.value.defaultModel
  const r = await fetch('/api/v1/settings/gateway-nodes/upsert', { method: 'POST', headers: authHeaders(), body: JSON.stringify(editingNode.value) })
  if (r.ok) { saveMsg.value = '节点已保存'; cancelEdit(); await loadNodes() } else { saveMsg.value = '保存失败: ' + (await r.text()) }
}
async function deleteNode(id: string) { if (!confirm('确定删除？')) return; await fetch(`/api/v1/settings/gateway-nodes/${encodeURIComponent(id)}`, { method: 'DELETE', headers: authHeaders() }); await loadNodes() }
async function moveNode(idx: number, dir: -1|1) {
  const arr = [...nodes.value]; const t = idx + dir; if (t < 0 || t >= arr.length) return
  ;[arr[idx], arr[t]] = [arr[t], arr[idx]]
  await fetch('/api/v1/settings/gateway-nodes/reorder', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ node_ids: arr.map(n => n.id) }) })
  await loadNodes()
}
async function testConnection() {
  if (!editingNode.value) return; testBusy.value = true; testResult.value = null
  try {
    const r = await fetch('/api/v1/settings/test-connection', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ provider: selectedProvider.value.key, api_key: editingNode.value.api_key, base_url: editingNode.value.base_url, model: editingNode.value.model }) })
    testResult.value = (await r.json()).result as TestResult
  } catch { testResult.value = { provider: '', model: '', ok: false, error: '请求失败' } } finally { testBusy.value = false }
}
onMounted(() => loadNodes())
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-4xl mx-auto">
      <div class="flex items-center justify-between mb-6">
        <div>
          <h2 class="text-lg font-black">Agent 网关</h2>
          <p class="text-[11px] text-[#64748b] mt-0.5">管理 LLM 网关节点，支持 Ark / Claude / Qwen / OpenAI 四种适配器。网关自动将不同 LLM 格式转换到系统统一 Schema。</p>
        </div>
        <button class="bg-[#363e42] text-white px-5 py-2.5 rounded-xl font-bold text-[13px] shadow-sm" @click="startAdd">+ 添加节点</button>
      </div>

      <!-- 节点列表 -->
      <div v-if="nodes.length" class="space-y-2 mb-8">
        <div v-for="(node, idx) in nodes" :key="node.id" class="bg-white rounded-xl border p-4 flex items-center gap-4" :class="node.status === 'active' ? 'border-[#e2e8f0]' : 'border-orange-200 opacity-70'">
          <span class="text-[10px] text-[#94a3b8] font-mono w-6 shrink-0">#{{ idx + 1 }}</span>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span class="font-bold text-[13px]">{{ node.name || node.id }}</span>
              <span class="text-[10px] px-2 py-0.5 rounded-full font-bold" :class="node.status==='active'?'bg-green-100 text-green-700':node.status==='degraded'?'bg-amber-100 text-amber-700':'bg-gray-100 text-gray-500'">{{ statusLabel(node.status) }}</span>
              <span class="text-[10px] text-[#64748b] bg-[#f1f5f9] px-2 py-0.5 rounded-full">{{ providerLabel(node.provider) }}</span>
            </div>
            <div class="text-[11px] text-[#64748b] truncate">{{ node.model }}<span v-if="node.endpoint_id" class="ml-2 text-[#94a3b8]">端点: {{ node.endpoint_id }}</span></div>
          </div>
          <div class="flex items-center gap-1 shrink-0">
            <button class="text-[11px] px-2 py-1 border rounded" :disabled="idx===0" @click="moveNode(idx,-1)">↑</button>
            <button class="text-[11px] px-2 py-1 border rounded" :disabled="idx===nodes.length-1" @click="moveNode(idx,1)">↓</button>
            <button class="text-[11px] px-3 py-1 border rounded text-[#d97706] font-bold" @click="startEdit(node)">编辑</button>
            <button class="text-[11px] px-3 py-1 border rounded text-red-500 font-bold" @click="deleteNode(node.id)">删除</button>
          </div>
        </div>
      </div>
      <div v-else class="text-center py-16 text-[#94a3b8] text-sm">暂无网关节点<br><button class="mt-3 text-[#d97706] font-bold text-[12px] underline" @click="startAdd">添加第一个节点</button></div>

      <!-- 编辑表单 -->
      <div v-if="showForm && editingNode" class="bg-white rounded-2xl border shadow-sm p-6 space-y-5">
        <h3 class="font-bold text-[15px]">{{ editingNode.id.includes('node_') && !editingNode.name ? '添加网关节点' : '编辑网关节点' }}</h3>

        <!-- 运营商选择 -->
        <div>
          <label class="block text-[12px] font-bold text-[#1e293b] mb-2">选择运营商（适配器类型）</label>
          <div class="grid grid-cols-4 gap-2">
            <button v-for="p in PROVIDERS" :key="p.key" class="text-[12px] font-bold py-2.5 px-3 rounded-xl border-2 transition-all"
              :class="selectedProvider.key===p.key?'border-[#2563eb] bg-[#eff6ff] text-[#1d4ed8] shadow-sm':'border-[#e2e8f0] hover:border-[#cbd5e1] text-[#64748b]'"
              @click="selectedProvider=p; editingNode.provider=p.key">{{ p.label }}</button>
          </div>
          <p class="text-[10px] text-[#94a3b8] mt-1.5">{{ selectedProvider.key==='ark'?'OpenAI 兼容协议，通过火山方舟 ARK 推理端点调用':selectedProvider.key==='claude'?'Anthropic Messages API，system 在顶层，content 为数组格式':selectedProvider.key==='qwen'?'DashScope OpenAI 兼容模式，需 X-DashScope 头部':'标准 OpenAI Chat Completions API' }}</p>
        </div>

        <div class="grid grid-cols-3 gap-4">
          <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">节点 ID</span><input v-model="editingNode.id" class="border rounded-lg px-3 py-2 text-[12px] font-mono" placeholder="node_primary" /></label>
          <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">节点名称</span><input v-model="editingNode.name" class="border rounded-lg px-3 py-2 text-[12px]" placeholder="主推理节点" /></label>
          <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">状态</span>
            <select v-model="editingNode.status" class="border rounded-lg px-3 py-2 text-[12px]"><option value="active">启用</option><option value="degraded">降级</option><option value="disabled">禁用</option></select></label>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">模型</span><input v-model="editingNode.model" class="border rounded-lg px-3 py-2 text-[12px] font-mono" :placeholder="selectedProvider.defaultModel" /></label>
          <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">API 地址</span><input v-model="editingNode.base_url" class="border rounded-lg px-3 py-2 text-[12px] font-mono" :placeholder="selectedProvider.defaultBaseUrl" /></label>
        </div>
        <div v-if="selectedProvider.needsEndpoint" class="grid grid-cols-2 gap-4">
          <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">{{ selectedProvider.endpointLabel }}</span><input v-model="editingNode.endpoint_id" class="border rounded-lg px-3 py-2 text-[12px] font-mono" :placeholder="selectedProvider.endpointHint" /></label>
        </div>
        <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">API Key</span><input v-model="editingNode.api_key" type="password" class="border rounded-lg px-3 py-2 text-[12px] font-mono" :placeholder="selectedProvider.key==='ark'?'火山方舟 API Key':selectedProvider.key==='claude'?'sk-ant-xxx':'sk-xxx'" /></label>
        <div class="grid grid-cols-3 gap-4">
          <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">优先级</span><input v-model.number="editingNode.priority" type="number" class="border rounded-lg px-3 py-2 text-[12px]" min="1" max="999" /></label>
          <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">权重</span><input v-model.number="editingNode.weight" type="number" class="border rounded-lg px-3 py-2 text-[12px]" min="0" max="1000" /></label>
          <label class="flex flex-col gap-1"><span class="text-[11px] font-bold text-[#64748b]">任务标签</span><input :value="(editingNode.tags||[]).join(', ')" class="border rounded-lg px-3 py-2 text-[12px]" placeholder="qa, summary" @input="editingNode.tags=($event.target as HTMLInputElement).value.split(',').map(s=>s.trim()).filter(Boolean)" /></label>
        </div>

        <div v-if="testResult" class="text-[12px] p-3 rounded-lg" :class="testResult.ok?'bg-green-50 text-green-700 border border-green-200':'bg-red-50 text-red-700 border border-red-200'">
          <template v-if="testResult.ok">连接成功 — {{ testResult.provider }} / {{ testResult.model }} — 延迟 {{ testResult.latency_ms }}ms — HTTP {{ testResult.status_code }}</template>
          <template v-else>连接失败 — {{ testResult.error || '未知错误' }}</template>
        </div>
        <div v-if="saveMsg" class="text-[12px] px-3 py-2 rounded-lg" :class="saveMsg.includes('失败')?'bg-red-50 text-red-600':'bg-green-50 text-green-600'">{{ saveMsg }}</div>

        <div class="flex gap-3 pt-2">
          <button class="bg-[#2563eb] text-white px-6 py-2.5 rounded-xl font-bold text-[13px] shadow-sm disabled:opacity-50" @click="saveNode">保存节点</button>
          <button class="border-2 border-[#e2e8f0] px-6 py-2.5 rounded-xl text-[13px] font-bold disabled:opacity-50" :disabled="testBusy" @click="testConnection">{{ testBusy?'测试中...':'测试连接' }}</button>
          <button class="text-[#94a3b8] text-[13px] px-4 py-2.5" @click="cancelEdit">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>
