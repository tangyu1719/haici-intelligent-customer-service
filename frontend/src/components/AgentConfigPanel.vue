<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface AgentCatalogItem {
  agent_key: string
  label: string
  group: string
  kind: string
  hint?: string
  variables?: string[]
  has_override?: boolean
  builtin_exists?: boolean
}

const loading = ref(false)
const msg = ref('')
const catalog = ref<AgentCatalogItem[]>([])
const selectedKey = ref('')
const mdContent = ref('')
const GROUP_LABELS: Record<string, string> = {
  multimodal_image_vlm: 'VLM 图片理解（视觉语言模型直接描述图片）',
  multimodal_image_ocr: 'OCR + LLM 图片描述（OCR提取文字 → LLM合成描述）',
  doc_normalize: '文档标准化与摘要',
  chat_agent: 'AI 问答与运维',
}

const KIND_LABELS: Record<string, string> = {
  vlm: 'VLM',
  llm: 'LLM',
}

/** 按 group+kind 分组 */
const groupedAgents = computed(() => {
  const m: Record<string, AgentCatalogItem[]> = {}
  for (const a of catalog.value) {
    // VLM类型的multimodal_image → multimodal_image_vlm
    // LLM类型的multimodal_image → multimodal_image_ocr
    let gk = a.group || 'other'
    if (gk === 'multimodal_image') {
      gk = a.kind === 'vlm' ? 'multimodal_image_vlm' : 'multimodal_image_ocr'
    }
    if (!m[gk]) m[gk] = []
    m[gk].push(a)
  }
  return m
})

const selectedMeta = computed(() => catalog.value.find((a) => a.agent_key === selectedKey.value))

async function loadCatalog() {
  const r = await fetch('/api/v1/settings/agents/catalog', { headers: authHeaders() })
  const d = await r.json()
  catalog.value = d.agents || []
}

async function loadMd(key: string) {
  loading.value = true
  msg.value = ''
  try {
    const r = await fetch(`/api/v1/settings/agents-md/${encodeURIComponent(key)}`, {
      headers: authHeaders(),
    })
    const d = await r.json()
    mdContent.value = d.content || ''
    selectedKey.value = key
  } catch (e: unknown) {
    msg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function saveMd() {
  if (!selectedKey.value) return
  loading.value = true
  msg.value = ''
  try {
    const r = await fetch(`/api/v1/settings/agents-md/${encodeURIComponent(selectedKey.value)}`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: mdContent.value }),
    })
    if (!r.ok) throw new Error('保存失败')
    msg.value = 'Prompt 已保存到 backend/data/agents/ 和 agent_config.json'
    await loadCatalog()
  } catch (e: unknown) {
    msg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function braceVar(v: string): string {
  return '{' + v + '}'
}

onMounted(async () => {
  loading.value = true
  try {
    await loadCatalog()
    if (catalog.value.length) {
      selectedKey.value = catalog.value[0].agent_key
      await loadMd(selectedKey.value)
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="p-6 overflow-y-auto h-full">
    <div class="max-w-6xl mx-auto">
      <h2 class="text-lg font-black mb-1">Agent 配置</h2>
      <p class="text-[11px] text-[#64748b] mb-1">
        管理系统中所有已注册 Agent 的 Prompt 模板，修改后直接写入
        <code class="bg-[#f1f5f9] px-1 rounded">backend/data/agents/{agent_key}/AGENT.md</code>
        ，重启后自动生效。
      </p>
      <p v-if="msg" class="text-[12px] py-1 px-2 rounded mb-2" :class="msg.includes('失败') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'">{{ msg }}</p>

      <div class="flex gap-4 mt-4">
        <!-- 左侧Agent导航 -->
        <aside class="w-[260px] shrink-0 border rounded-xl overflow-hidden max-h-[calc(100vh-240px)] overflow-y-auto">
          <div v-for="(items, gk) in groupedAgents" :key="gk" class="border-b last:border-b-0">
            <div class="px-3 py-2 text-[11px] font-bold text-[#64748b] bg-[#fafafa] sticky top-0">
              {{ GROUP_LABELS[gk] || gk }}
            </div>
            <button
              v-for="a in items"
              :key="a.agent_key"
              type="button"
              class="w-full text-left px-4 py-2.5 text-[12px] border-b border-[#f1f5f9] last:border-b-0 transition-colors flex items-center justify-between gap-2"
              :class="selectedKey === a.agent_key ? 'bg-[#eff6ff] text-[#1d4ed8] font-bold' : 'hover:bg-[#f8fafc]'"
              @click="loadMd(a.agent_key)"
            >
              <span class="truncate">{{ a.label }}</span>
              <span class="flex items-center gap-1 shrink-0">
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-bold"
                  :class="a.kind === 'vlm' ? 'bg-purple-100 text-purple-600' : 'bg-blue-100 text-blue-600'"
                >{{ KIND_LABELS[a.kind] || a.kind }}</span>
                <span v-if="a.has_override" class="text-[9px] bg-[#fef3c7] text-[#92400e] px-1 rounded">已改</span>
              </span>
            </button>
          </div>
        </aside>

        <!-- 右侧编辑区 -->
        <main class="flex-1 min-w-0 border rounded-xl p-4">
          <template v-if="selectedMeta">
            <div class="flex items-center gap-3 mb-3 pb-3 border-b">
              <div>
                <h3 class="font-bold text-[14px]">{{ selectedMeta.label }}</h3>
                <p class="text-[11px] text-[#64748b]">{{ selectedMeta.hint }}</p>
              </div>
              <span class="ml-auto text-[10px] px-2 py-1 rounded-full font-bold"
                :class="selectedMeta.kind === 'vlm' ? 'bg-purple-100 text-purple-600' : 'bg-blue-100 text-blue-600'"
              >{{ KIND_LABELS[selectedMeta.kind] || selectedMeta.kind }}</span>
            </div>
            <div class="mb-3 text-[11px] text-[#64748b]">
              <span class="font-bold">Agent Key:</span> <code class="bg-[#f1f5f9] px-1 rounded text-[10px]">{{ selectedMeta.agent_key }}</code>
              <span v-if="selectedMeta.variables?.length" class="ml-4">
                <span class="font-bold">变量:</span>
                <code v-for="v in selectedMeta.variables" :key="v" class="bg-[#fef3c7] px-1 rounded text-[10px] ml-1">{{ braceVar(v) }}</code>
              </span>
            </div>

            <label class="block text-[11px] font-bold text-[#64748b] mb-1">AGENT.md / Prompt 内容（直接编辑保存）</label>
            <textarea
              v-model="mdContent"
              class="w-full min-h-[350px] font-mono text-[12px] leading-relaxed p-3 border rounded-lg resize-y focus:outline-none focus:border-[#2563eb]"
              spellcheck="false"
              :disabled="loading"
              placeholder="加载中..."
            />

            <div class="flex gap-2 mt-3">
              <button type="button" class="bg-[#2563eb] text-white px-5 py-2 rounded-lg font-bold text-[12px] disabled:opacity-50" :disabled="loading" @click="saveMd">
                保存 Prompt
              </button>
              <span class="text-[11px] text-[#64748b] self-center">保存到 backend/data/agents/{{ selectedMeta.agent_key }}/AGENT.md</span>
            </div>
          </template>
          <div v-else class="text-center py-16 text-[#64748b] text-sm">请从左侧选择一个 Agent</div>

        </main>
      </div>
    </div>
  </div>
</template>
