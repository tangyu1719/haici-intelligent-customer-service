<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface GatewayNode {
  id: string
  name: string
  provider: string
  base_url: string
  api_key: string
  endpoint_id: string
  model: string
  priority: number
  weight: number
  status: string
  tags: string[]
}

interface GatewaySnapshot {
  route_mode: string
  task_type_route: Record<string, unknown>
  nodes: GatewayNode[]
  node_count: number
  total_nodes: number
}

interface TestResult {
  provider: string
  model: string
  ok: boolean
  status_code?: number
  latency_ms?: number
  error?: string
}

const nodes = ref<GatewayNode[]>([])
const snapshot = ref<GatewaySnapshot | null>(null)
const editingNode = ref<GatewayNode | null>(null)
const showForm = ref(false)
const testResult = ref<TestResult | null>(null)
const testBusy = ref(false)

const providerLabel = (p: string): string => {
  const map: Record<string, string> = {
    ark: '火山方舟 ARK',
    claude: 'Anthropic Claude',
    anthropic: 'Anthropic Claude',
    qwen: '通义千问',
    openai: 'OpenAI',
    openai_compatible: 'OpenAI 兼容',
  }
  return map[p] || p || '未知'
}

const statusLabel = (s: string): string => {
  const map: Record<string, string> = {
    active: '启用',
    disabled: '禁用',
    degraded: '降级',
  }
  return map[s] || s
}

const providerOptions = [
  { value: 'ark', label: '火山方舟 ARK' },
  { value: 'claude', label: 'Anthropic Claude' },
  { value: 'qwen', label: '通义千问' },
  { value: 'openai', label: 'OpenAI' },
]

const loadNodes = async (): Promise<void> => {
  const res = await fetch('/api/v1/settings/gateway-nodes', { headers: authHeaders() })
  if (res.ok) {
    const data = await res.json()
    nodes.value = data.nodes || []
  }
}

const loadSnapshot = async (): Promise<void> => {
  try {
    const res = await fetch('/api/v1/settings/gateway-snapshot', { headers: authHeaders() })
    if (res.ok) snapshot.value = await res.json()
  } catch { /* ignore */ }
}

const newEmpty = (): GatewayNode => ({
  id: 'node_' + Date.now(),
  name: '', provider: 'ark', base_url: '', api_key: '',
  endpoint_id: '', model: '', priority: 10, weight: 100,
  status: 'active', tags: [],
})

const startAdd = (): void => {
  editingNode.value = newEmpty()
  showForm.value = true
}

const startEdit = (n: GatewayNode): void => {
  editingNode.value = { ...n, tags: [...n.tags] }
  showForm.value = true
}

const cancelEdit = (): void => {
  editingNode.value = null
  showForm.value = false
}

const saveNode = async (): Promise<void> => {
  if (!editingNode.value) return
  const res = await fetch('/api/v1/settings/gateway-nodes/upsert', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(editingNode.value),
  })
  if (res.ok) {
    cancelEdit()
    await loadNodes()
    await loadSnapshot()
  }
}

const deleteNode = async (id: string): Promise<void> => {
  if (!window.confirm('确定删除该网关节点？')) return
  await fetch(`/api/v1/settings/gateway-nodes/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  await loadNodes()
  await loadSnapshot()
}

const moveNode = async (index: number, direction: -1 | 1): Promise<void> => {
  const arr = [...nodes.value]
  const target = index + direction
  if (target < 0 || target >= arr.length) return
  ;[arr[index], arr[target]] = [arr[target], arr[index]]
  const ids = arr.map((n) => n.id)
  await fetch('/api/v1/settings/gateway-nodes/reorder', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ node_ids: ids }),
  })
  await loadNodes()
}

const testConnection = async (): Promise<void> => {
  if (!editingNode.value) return
  testBusy.value = true
  testResult.value = null
  try {
    const res = await fetch('/api/v1/settings/test-connection', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        provider: editingNode.value.provider,
        api_key: editingNode.value.api_key,
        base_url: editingNode.value.base_url,
        model: editingNode.value.model,
      }),
    })
    const data = await res.json()
    testResult.value = data.result as TestResult
  } catch {
    testResult.value = { provider: '', model: '', ok: false, error: '请求失败' }
  } finally {
    testBusy.value = false
  }
}

const tagStr = (node: GatewayNode): string => {
  return (node.tags || []).join(', ')
}

onMounted(() => {
  loadNodes()
  loadSnapshot()
})
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-5xl mx-auto">
      <div class="flex flex-wrap justify-between items-center gap-3 mb-6">
        <h2 class="text-lg font-black">Agent 网关</h2>
        <div class="flex items-center gap-3">
          <span v-if="snapshot" class="text-[11px] text-[#363e42]/50">
            模式: {{ snapshot.route_mode }} ·
            节点: {{ snapshot.node_count }}/{{ snapshot.total_nodes }}
          </span>
          <button type="button" class="bg-[#363e42] text-white px-5 py-2.5 rounded-xl font-bold text-[13px]" @click="startAdd">
            + 添加节点
          </button>
        </div>
      </div>

      <p class="text-[11px] text-[#363e42]/50 mb-4">
        LLM 网关管理：支持 Ark（火山方舟）、Claude（Anthropic）、Qwen（通义千问）、OpenAI 四种适配器。
        网关自动将不同 LLM 的请求/响应格式转换到系统统一 Schema。
      </p>

      <!-- 节点列表 -->
      <div v-if="nodes.length" class="space-y-3 mb-6">
        <div
          v-for="(node, idx) in nodes"
          :key="node.id"
          class="bg-white rounded-xl border p-4 flex flex-wrap items-center gap-3"
          :class="node.status === 'active' ? 'border-[#363e42]/10' : 'border-[#d97706]/30 opacity-60'"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span class="font-bold text-[13px]">{{ node.name || node.id }}</span>
              <span class="text-[10px] px-2 py-0.5 rounded-full font-bold"
                :class="node.status === 'active' ? 'bg-green-100 text-green-700' : node.status === 'degraded' ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-500'"
              >
                {{ statusLabel(node.status) }}
              </span>
              <span class="text-[10px] text-[#363e42]/50">{{ providerLabel(node.provider) }}</span>
            </div>
            <div class="text-[11px] text-[#363e42]/60 truncate">
              {{ node.model || '(未配置模型)' }}
              <span v-if="node.endpoint_id" class="ml-2">端点: {{ node.endpoint_id }}</span>
            </div>
            <div class="text-[10px] text-[#363e42]/40 mt-0.5">
              优先级: {{ node.priority }} · 权重: {{ node.weight }}
              <span v-if="node.tags?.length" class="ml-2">标签: {{ tagStr(node) }}</span>
            </div>
          </div>
          <div class="flex items-center gap-1">
            <button type="button" class="text-[11px] px-2 py-1 border rounded font-bold" :disabled="idx === 0" @click="moveNode(idx, -1)">↑</button>
            <button type="button" class="text-[11px] px-2 py-1 border rounded font-bold" :disabled="idx === nodes.length - 1" @click="moveNode(idx, 1)">↓</button>
            <button type="button" class="text-[11px] px-3 py-1 border rounded text-[#d97706] font-bold" @click="startEdit(node)">编辑</button>
            <button type="button" class="text-[11px] px-3 py-1 border rounded text-red-500 font-bold" @click="deleteNode(node.id)">删除</button>
          </div>
        </div>
      </div>
      <div v-else class="text-center py-12 text-[#363e42]/40 text-sm">暂无网关节点，点击"+ 添加节点"创建</div>

      <!-- 编辑表单 -->
      <div v-if="showForm && editingNode" class="bg-white rounded-2xl border p-6 mt-4 space-y-4 max-w-2xl">
        <h3 class="font-bold text-[14px] mb-3">{{ editingNode.id.includes('node_') && !editingNode.name ? '添加节点' : '编辑节点' }}</h3>
        <div class="grid grid-cols-2 gap-4">
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60">
            节点 ID
            <input v-model="editingNode.id" type="text" class="border rounded-lg px-3 py-2 text-[12px]" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60">
            名称
            <input v-model="editingNode.name" type="text" class="border rounded-lg px-3 py-2 text-[12px]" placeholder="主节点" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60">
            提供商
            <select v-model="editingNode.provider" class="border rounded-lg px-3 py-2 text-[12px]">
              <option v-for="p in providerOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60">
            模型
            <input v-model="editingNode.model" type="text" class="border rounded-lg px-3 py-2 text-[12px]" placeholder="ep-xxx 或 gpt-4" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60 col-span-2">
            API 地址
            <input v-model="editingNode.base_url" type="text" class="border rounded-lg px-3 py-2 text-[12px]" :placeholder="editingNode.provider === 'claude' ? 'https://api.anthropic.com' : 'https://ark.cn-beijing.volces.com/api/v3'" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60 col-span-2">
            API Key
            <input v-model="editingNode.api_key" type="password" class="border rounded-lg px-3 py-2 text-[12px]" placeholder="sk-xxx 或 ep-xxx" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60">
            端点 ID (Ark专用)
            <input v-model="editingNode.endpoint_id" type="text" class="border rounded-lg px-3 py-2 text-[12px]" placeholder="ep-xxx" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60">
            优先级 (数字越小越优先)
            <input v-model.number="editingNode.priority" type="number" class="border rounded-lg px-3 py-2 text-[12px]" min="1" max="999" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60">
            权重
            <input v-model.number="editingNode.weight" type="number" class="border rounded-lg px-3 py-2 text-[12px]" min="0" max="1000" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60">
            状态
            <select v-model="editingNode.status" class="border rounded-lg px-3 py-2 text-[12px]">
              <option value="active">启用</option>
              <option value="degraded">降级</option>
              <option value="disabled">禁用</option>
            </select>
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#363e42]/60">
            标签 (逗号分隔)
            <input v-model="editingNode.tags" type="text" class="border rounded-lg px-3 py-2 text-[12px]" placeholder="qa,summary" @input="(e) => { const v = (e.target as HTMLInputElement).value; editingNode!.tags = v ? v.split(',').map((s: string) => s.trim()) : []; }" />
          </label>
        </div>

        <!-- 测试结果 -->
        <div v-if="testResult" class="text-[12px] p-3 rounded-lg" :class="testResult.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'">
          <template v-if="testResult.ok">
            连接成功: {{ testResult.provider }} / {{ testResult.model }} ·
            延迟 {{ testResult.latency_ms }}ms · HTTP {{ testResult.status_code }}
          </template>
          <template v-else>
            连接失败: {{ testResult.error || '未知错误' }}
          </template>
        </div>

        <div class="flex gap-3">
          <button type="button" class="bg-[#363e42] text-white px-5 py-2 rounded-xl font-bold text-[13px]" @click="saveNode">保存</button>
          <button type="button" class="border px-5 py-2 rounded-xl text-[13px] font-bold" :disabled="testBusy" @click="testConnection">
            {{ testBusy ? '测试中...' : '测试连接' }}
          </button>
          <button type="button" class="text-[#363e42]/50 text-[13px]" @click="cancelEdit">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>
