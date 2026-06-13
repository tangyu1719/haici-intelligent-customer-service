<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface MetadataField {
  key: string; label: string; description: string
}
interface SummaryCfg { enabled: boolean; prompt: string; max_length: number }
interface MetadataCfg { enabled: boolean; fields: MetadataField[] }
interface StructureCheckCfg { enabled: boolean; prompt: string; min_size_bytes: number; max_images_check: number }

const tab = ref<'summary' | 'metadata' | 'structure'>('summary')
const msg = ref('')
const busy = ref(false)

// 摘要整理
const summary = ref<SummaryCfg>({ enabled: true, prompt: '', max_length: 200 })
// 元数据
const metadata = ref<MetadataCfg>({ enabled: true, fields: [] })
const editField = ref<MetadataField | null>(null)
const editIdx = ref(-1)
// 结构化检查
const structureCheck = ref<StructureCheckCfg>({ enabled: true, prompt: '', min_size_bytes: 100, max_images_check: 50 })

async function loadAll() {
  busy.value = true
  try {
    const r = await fetch('/api/v1/structured/config', { headers: authHeaders() })
    const d = await r.json()
    summary.value = d.summary || { enabled: true, prompt: '', max_length: 200 }
    metadata.value = d.metadata || { enabled: true, fields: [] }
    structureCheck.value = d.structure_check || { enabled: true, prompt: '', min_size_bytes: 100, max_images_check: 50 }
  } catch (e: any) { msg.value = '加载失败: ' + (e.message || '') }
  finally { busy.value = false }
}

async function saveSummary() {
  busy.value = true; msg.value = ''
  try {
    const r = await fetch('/api/v1/structured/summary', {
      method: 'PUT', headers: authHeaders(),
      body: JSON.stringify(summary.value),
    })
    if (r.ok) msg.value = '摘要配置已保存'
    else msg.value = '保存失败'
  } catch (e: any) { msg.value = e.message || '保存失败' }
  finally { busy.value = false }
}

// ── 元数据字段管理 ──
function startAddField() {
  editField.value = { key: '', label: '', description: '' }
  editIdx.value = -1
}
function startEditField(idx: number) {
  editField.value = { ...metadata.value.fields[idx] }
  editIdx.value = idx
}
function cancelEditField() { editField.value = null; editIdx.value = -1 }
function saveField() {
  if (!editField.value) return
  if (!editField.value.key.trim() || !editField.value.label.trim()) {
    msg.value = '字段名和显示名不能为空'; return
  }
  if (editIdx.value >= 0) {
    metadata.value.fields[editIdx.value] = { ...editField.value }
  } else {
    metadata.value.fields.push({ ...editField.value })
  }
  cancelEditField()
}
function removeField(idx: number) {
  if (!confirm('确定删除该元数据字段？已提取的数据不受影响。')) return
  metadata.value.fields.splice(idx, 1)
}

async function saveMetadata() {
  busy.value = true; msg.value = ''
  try {
    const r = await fetch('/api/v1/structured/metadata', {
      method: 'PUT', headers: authHeaders(),
      body: JSON.stringify({ enabled: metadata.value.enabled, fields: metadata.value.fields }),
    })
    if (r.ok) msg.value = '元数据配置已保存'
    else msg.value = '保存失败'
  } catch (e: any) { msg.value = e.message || '保存失败' }
  finally { busy.value = false }
}

async function saveStructureCheck() {
  busy.value = true; msg.value = ''
  try {
    const r = await fetch('/api/v1/structured/structure-check', {
      method: 'PUT', headers: authHeaders(),
      body: JSON.stringify(structureCheck.value),
    })
    if (r.ok) msg.value = '检查配置已保存'
    else msg.value = '保存失败'
  } catch (e: any) { msg.value = e.message || '保存失败' }
  finally { busy.value = false }
}

onMounted(loadAll)
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-4xl mx-auto">
      <h2 class="text-lg font-black mb-1">结构化处理</h2>
      <p class="text-[11px] text-[#64748b] mb-4">
        多模态文档导入后的 AI 结构化处理：摘要整理、元数据提取、内容结构检查。
      </p>

      <p v-if="msg" class="text-[12px] py-1 px-2 rounded mb-3" :class="msg.includes('失败') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'">{{ msg }}</p>

      <!-- Tab导航 -->
      <div class="flex gap-0 mb-6 border-b">
        <button v-for="t in [{k:'summary',l:'摘要整理'},{k:'metadata',l:'元数据提取'},{k:'structure',l:'结构化检查'}]" :key="t.k"
          class="px-5 py-2.5 text-[13px] font-bold border-b-2 transition-colors"
          :class="tab === t.k ? 'border-[#2563eb] text-[#1d4ed8]' : 'border-transparent text-[#64748b] hover:text-[#1e293b]'"
          @click="tab = t.k as any"
        >{{ t.l }}</button>
      </div>

      <!-- ═══ 摘要整理 ═══ -->
      <div v-if="tab === 'summary'" class="space-y-4">
        <div class="flex items-center gap-3">
          <label class="flex items-center gap-2 cursor-pointer">
            <input v-model="summary.enabled" type="checkbox" class="rounded" />
            <span class="text-[12px] font-bold">启用摘要整理</span>
          </label>
          <span class="text-[11px] text-[#64748b]">导入文档后自动用 AI 生成内容摘要</span>
        </div>
        <div>
          <label class="block text-[11px] font-bold text-[#64748b] mb-1">摘要 Prompt（AI 据此生成摘要）</label>
          <textarea v-model="summary.prompt" rows="8"
            class="w-full border rounded-lg p-3 text-[12px] font-mono leading-relaxed resize-y focus:outline-none focus:border-[#2563eb]"
            :disabled="!summary.enabled" />
          <p class="text-[10px] text-[#94a3b8] mt-1">
            摘要描述的是"文档涉及了哪些方面/话题"，不是具体数据结论。
            例如：本文档介绍了公司产品的功能特性、定价策略以及售后服务政策。
          </p>
        </div>
        <div class="flex items-center gap-2">
          <label class="text-[11px] font-bold text-[#64748b]">摘要最大长度（字）</label>
          <input v-model.number="summary.max_length" type="number" min="50" max="1000"
            class="border rounded-lg px-3 py-1.5 text-[12px] w-24" :disabled="!summary.enabled" />
        </div>
        <button class="bg-[#2563eb] text-white px-5 py-2 rounded-lg font-bold text-[12px] disabled:opacity-50"
          :disabled="busy" @click="saveSummary">保存配置</button>
      </div>

      <!-- ═══ 元数据提取 ═══ -->
      <div v-if="tab === 'metadata'" class="space-y-4">
        <div class="flex items-center gap-3 mb-4">
          <label class="flex items-center gap-2 cursor-pointer">
            <input v-model="metadata.enabled" type="checkbox" class="rounded" />
            <span class="text-[12px] font-bold">启用元数据提取</span>
          </label>
          <span class="text-[11px] text-[#64748b]">AI 自动根据字段名理解含义并提取文档元数据</span>
        </div>

        <div class="bg-[#f8fafc] rounded-xl border p-4 mb-4">
          <h4 class="text-[11px] font-bold text-[#64748b] mb-2">工作原理</h4>
          <ol class="text-[11px] text-[#64748b] space-y-1 list-decimal list-inside">
            <li>您在下表中定义元数据字段（字段名 + 中文说明）</li>
            <li>AI 根据字段说明自动理解该字段的含义</li>
            <li>文档导入后 AI 自动提取元数据并以 JSON 格式存储</li>
            <li>您可以在前端审核、修改确认提取结果</li>
          </ol>
        </div>

        <!-- 字段表格 -->
        <div class="border rounded-xl overflow-hidden">
          <table class="w-full text-[12px]">
            <thead class="bg-[#f8fafc] text-[#64748b] text-left">
              <tr><th class="p-3 w-[120px]">字段名(key)</th><th class="p-3 w-[120px]">显示名</th><th class="p-3">说明</th><th class="p-3 w-[80px]">操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="(f, i) in metadata.fields" :key="i" class="border-t hover:bg-[#f8fafc]">
                <td class="p-3 font-mono text-[11px]">{{ f.key }}</td>
                <td class="p-3">{{ f.label }}</td>
                <td class="p-3 text-[#64748b] text-[11px]">{{ f.description }}</td>
                <td class="p-3 flex gap-1">
                  <button class="text-[11px] text-[#2563eb] font-bold" @click="startEditField(i)">编辑</button>
                  <button class="text-[11px] text-red-500" @click="removeField(i)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="!metadata.fields.length" class="p-6 text-center text-[#94a3b8] text-[12px]">
            暂无元数据字段，点击下方按钮添加
          </div>
        </div>

        <!-- 编辑/添加字段表单 -->
        <div v-if="editField" class="bg-white border-2 border-[#2563eb] rounded-xl p-4 space-y-3">
          <h4 class="text-[12px] font-bold">{{ editIdx >= 0 ? '编辑字段' : '添加字段' }}</h4>
          <div class="grid grid-cols-3 gap-3">
            <label class="flex flex-col gap-1 text-[11px] font-bold text-[#64748b]">
              字段名（英文key）
              <input v-model="editField.key" class="border rounded-lg px-3 py-2 text-[12px] font-mono" placeholder="doc_type" :disabled="editIdx>=0" />
            </label>
            <label class="flex flex-col gap-1 text-[11px] font-bold text-[#64748b]">
              显示名（中文）
              <input v-model="editField.label" class="border rounded-lg px-3 py-2 text-[12px]" placeholder="文档类型" />
            </label>
            <label class="flex flex-col gap-1 text-[11px] font-bold text-[#64748b]">
              字段说明（给AI看的）
              <input v-model="editField.description" class="border rounded-lg px-3 py-2 text-[12px]" placeholder="如：产品手册/技术文档/FAQ" />
            </label>
          </div>
          <div class="flex gap-2">
            <button class="bg-[#2563eb] text-white px-4 py-1.5 rounded-lg text-[12px] font-bold" @click="saveField">确定</button>
            <button class="border px-4 py-1.5 rounded-lg text-[12px]" @click="cancelEditField">取消</button>
          </div>
        </div>

        <div class="flex gap-2">
          <button v-if="!editField" class="border-2 border-dashed border-[#cbd5e1] px-4 py-2 rounded-xl text-[12px] font-bold text-[#64748b] hover:border-[#2563eb] hover:text-[#2563eb]" @click="startAddField">
            + 添加字段
          </button>
          <button class="bg-[#2563eb] text-white px-5 py-2 rounded-lg font-bold text-[12px] disabled:opacity-50" :disabled="busy" @click="saveMetadata">
            保存元数据配置
          </button>
        </div>
      </div>

      <!-- ═══ 结构化检查 ═══ -->
      <div v-if="tab === 'structure'" class="space-y-4">
        <div class="flex items-center gap-3">
          <label class="flex items-center gap-2 cursor-pointer">
            <input v-model="structureCheck.enabled" type="checkbox" class="rounded" />
            <span class="text-[12px] font-bold">启用导入后结构化检查</span>
          </label>
        </div>
        <p class="text-[11px] text-[#64748b]">
          在多模态文档导入转化后，自动检查文档内容是否已有清晰结构。
          如果 MD 已有标题层级则保留；如果是聊天记录等杂乱内容，则标记需要重整理。
        </p>

        <div class="grid grid-cols-3 gap-4">
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#64748b]">
            最小检查体积（字节）
            <input v-model.number="structureCheck.min_size_bytes" type="number" min="10"
              class="border rounded-lg px-3 py-2 text-[12px]" :disabled="!structureCheck.enabled" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-bold text-[#64748b]">
            图片数量上限检查
            <input v-model.number="structureCheck.max_images_check" type="number" min="1" max="200"
              class="border rounded-lg px-3 py-2 text-[12px]" :disabled="!structureCheck.enabled" />
          </label>
        </div>

        <div>
          <label class="block text-[11px] font-bold text-[#64748b] mb-1">结构检查 Prompt</label>
          <textarea v-model="structureCheck.prompt" rows="6"
            class="w-full border rounded-lg p-3 text-[12px] font-mono leading-relaxed resize-y focus:outline-none focus:border-[#2563eb]"
            :disabled="!structureCheck.enabled" />
        </div>

        <button class="bg-[#2563eb] text-white px-5 py-2 rounded-lg font-bold text-[12px] disabled:opacity-50"
          :disabled="busy" @click="saveStructureCheck">保存配置</button>
      </div>
    </div>
  </div>
</template>
