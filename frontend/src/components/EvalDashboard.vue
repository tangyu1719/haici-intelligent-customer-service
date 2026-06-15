<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface MetricItem { key: string; name: string; layer: string; description: string; formula: string; range: string; threshold_ok: number; threshold_good: number; direction: string; unit: string; value: number; status: string; display_value: string }
interface LayerData { label: string; description: string; metrics: MetricItem[] }
interface FullReport { total: number; success_count: number; fail_count: number; period_days: number; generated_at: string; pipeline_stages: {id:string;label:string;icon:string}[]; layer1_retrieval: LayerData & {pass_at_1:number;pass_at_3:number;pass_at_5:number}; layer2_generation: LayerData; layer3_system: LayerData; items: any[] }

const days = ref(7)
const loading = ref(false)
const report = ref<FullReport | null>(null)
const expandedMetric = ref<string | null>(null)

async function load() {
  loading.value = true
  try {
    const r = await fetch(`/api/v1/admin/eval/rag-metrics/full-report?limit=100&days=${days.value}`, { headers: authHeaders() })
    if (r.ok) report.value = await r.json()
  } finally { loading.value = false }
}

const semoji = (s: string) => ({ good: '🟢', ok: '🟡', warn: '🔴' } as Record<string, string>)[s] || ''
const slab = (s: string) => ({ good: '优秀', ok: '正常', warn: '需优化' } as Record<string, string>)[s] || s

onMounted(load)
</script>

<template>
  <div class="p-6 overflow-y-auto h-full">
    <div class="max-w-7xl mx-auto">
      <div class="flex items-center justify-between mb-4">
        <div><h2 class="text-lg font-black">RAG 评测报告</h2><p class="text-[11px] text-[#64748b]">管线可视化 · 三层指标 · 定义/公式/阈值</p></div>
        <div class="flex items-center gap-3">
          <select v-model.number="days" class="border rounded px-2 py-1 text-[11px]" @change="load"><option :value="7">7天</option><option :value="14">14天</option><option :value="30">30天</option></select>
          <button class="text-[11px] font-bold px-3 py-1 rounded border" :disabled="loading" @click="load">刷新</button>
        </div>
      </div>

      <div v-if="loading" class="text-center py-16 text-[#94a3b8]">加载中...</div>

      <template v-if="report">
        <!-- 汇总 -->
        <div class="grid grid-cols-5 gap-3 mb-4">
          <div v-for="(card, i) in [
            {l:'评测样本',v:report.total,c:'text-[#363e42]'},
            {l:'成功率',v:((report.success_count/report.total)*100).toFixed(0)+'%',c:'text-green-500'},
            {l:'Pass@1',v:(report.layer1_retrieval.pass_at_1*100).toFixed(0)+'%',c:'text-[#2563eb]'},
            {l:'Pass@3',v:(report.layer1_retrieval.pass_at_3*100).toFixed(0)+'%',c:'text-[#2563eb]'},
            {l:'Pass@5',v:(report.layer1_retrieval.pass_at_5*100).toFixed(0)+'%',c:'text-[#2563eb]'},
          ]" :key="i" class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8]">{{ card.l }}</div>
            <div class="text-[24px] font-black" :class="card.c">{{ card.v }}</div>
          </div>
        </div>

        <!-- ═══ 管线图 ═══ -->
        <div class="bg-white border rounded-xl p-4 mb-4">
          <h3 class="text-[13px] font-black mb-3">RAG 评测管线</h3>
          <!-- 主流程 -->
          <div class="flex items-stretch gap-0 mb-4 overflow-x-auto pb-2">
            <template v-for="(s, i) in report.pipeline_stages" :key="s.id">
              <div class="flex flex-col items-center shrink-0" style="min-width:64px">
                <div class="w-10 h-10 rounded-xl flex items-center justify-center text-base shadow-sm"
                  :class="i<=3?'bg-blue-100 border-2 border-blue-300':i<=5?'bg-green-100 border-2 border-green-300':i<=7?'bg-purple-100 border-2 border-purple-300':'bg-amber-100 border-2 border-amber-300'">
                  {{ s.icon }}
                </div>
                <span class="text-[8px] mt-1 text-center leading-tight font-bold" :class="i<=3?'text-blue-600':i<=5?'text-green-600':i<=7?'text-purple-600':'text-amber-600'">{{ s.label }}</span>
              </div>
              <div v-if="i < report.pipeline_stages.length - 1" class="flex items-center shrink-0 px-1">
                <div class="flex flex-col items-center">
                  <span class="text-[16px] font-black text-[#cbd5e1]">→</span>
                </div>
              </div>
            </template>
          </div>
          <!-- 阶段标签 -->
          <div class="flex justify-between text-[9px] font-bold px-2">
            <span class="text-blue-500">← 检索阶段 →</span>
            <span class="text-green-500">← 生成阶段 →</span>
            <span class="text-purple-500">← 输出 →</span>
          </div>
        </div>

        <!-- ═══ 三层指标分类说明 ═══ -->
        <div class="grid grid-cols-3 gap-4 mb-4">
          <!-- 第一层：检索质量 -->
          <div class="bg-gradient-to-b from-blue-50 to-white border border-blue-100 rounded-xl p-4">
            <div class="flex items-center gap-2 mb-3 border-b border-blue-100 pb-2">
              <span class="text-xl">🔍</span>
              <div><h3 class="text-[13px] font-black text-blue-700">{{ report.layer1_retrieval.label }}</h3><p class="text-[9px] text-blue-500">{{ report.layer1_retrieval.description }}</p></div>
            </div>
            <div class="space-y-1.5">
              <div v-for="m in report.layer1_retrieval.metrics" :key="m.key" class="cursor-pointer" @click="expandedMetric = expandedMetric === m.key ? null : m.key">
                <div class="flex items-center justify-between text-[11px] bg-white rounded-lg px-2 py-1.5 border" :class="m.status==='warn'?'border-red-200':m.status==='good'?'border-green-200':'border-amber-200'">
                  <span class="font-bold">{{ m.name }}</span>
                  <div class="flex items-center gap-1">
                    <span class="font-mono font-black text-[12px]" :class="m.status==='warn'?'text-red-500':m.status==='good'?'text-green-500':'text-amber-500'">{{ m.display_value }}</span>
                    <span>{{ semoji(m.status) }}</span>
                  </div>
                </div>
                <div v-if="expandedMetric === m.key" class="bg-blue-50/50 rounded-lg p-2 mt-0.5 text-[9px] space-y-0.5 border border-blue-100">
                  <div><b>定义：</b>{{ m.description }}</div>
                  <div><b>计算：</b><code class="text-[8px] break-all">{{ m.formula }}</code></div>
                  <div><b>范围：</b>{{ m.range }} · 优秀≥{{ m.threshold_good }} · 正常≥{{ m.threshold_ok }} · 状态:{{ slab(m.status) }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 第二层：生成一致性 -->
          <div class="bg-gradient-to-b from-green-50 to-white border border-green-100 rounded-xl p-4">
            <div class="flex items-center gap-2 mb-3 border-b border-green-100 pb-2">
              <span class="text-xl">🤖</span>
              <div><h3 class="text-[13px] font-black text-green-700">{{ report.layer2_generation.label }}</h3><p class="text-[9px] text-green-500">{{ report.layer2_generation.description }}</p></div>
            </div>
            <div class="space-y-1.5">
              <div v-for="m in report.layer2_generation.metrics" :key="m.key" class="cursor-pointer" @click="expandedMetric = expandedMetric === m.key ? null : m.key">
                <div class="flex items-center justify-between text-[11px] bg-white rounded-lg px-2 py-1.5 border" :class="m.value===0?'border-gray-200':m.status==='warn'?'border-red-200':m.status==='good'?'border-green-200':'border-amber-200'">
                  <span class="font-bold">{{ m.name }}</span>
                  <div class="flex items-center gap-1">
                    <span class="font-mono font-black text-[12px]" :class="m.value===0?'text-[#94a3b8]':m.status==='warn'?'text-red-500':m.status==='good'?'text-green-500':'text-amber-500'">{{ m.value > 0 ? m.display_value : '待评测' }}</span>
                    <span v-if="m.value>0">{{ semoji(m.status) }}</span>
                  </div>
                </div>
                <div v-if="expandedMetric === m.key" class="bg-green-50/50 rounded-lg p-2 mt-0.5 text-[9px] space-y-0.5 border border-green-100">
                  <div><b>定义：</b>{{ m.description }}</div>
                  <div><b>计算：</b><code class="text-[8px] break-all">{{ m.formula }}</code></div>
                  <div><b>范围：</b>{{ m.range }} · 优秀≥{{ m.threshold_good }} · 正常≥{{ m.threshold_ok }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 第三层：系统工程 -->
          <div class="bg-gradient-to-b from-gray-50 to-white border border-gray-200 rounded-xl p-4">
            <div class="flex items-center gap-2 mb-3 border-b border-gray-200 pb-2">
              <span class="text-xl">⚙️</span>
              <div><h3 class="text-[13px] font-black text-gray-600">{{ report.layer3_system.label }}</h3><p class="text-[9px] text-gray-400">{{ report.layer3_system.description }}</p></div>
            </div>
            <div class="space-y-1.5">
              <div v-for="m in report.layer3_system.metrics" :key="m.key" class="cursor-pointer" @click="expandedMetric = expandedMetric === m.key ? null : m.key">
                <div class="flex items-center justify-between text-[11px] bg-white rounded-lg px-2 py-1.5 border" :class="m.status==='warn'?'border-red-200':m.status==='good'?'border-green-200':'border-amber-200'">
                  <span class="font-bold">{{ m.name }}</span>
                  <div class="flex items-center gap-1">
                    <span class="font-mono font-black text-[12px]" :class="m.status==='warn'?'text-red-500':m.status==='good'?'text-green-500':'text-amber-500'">{{ m.display_value }}{{ m.unit==='ratio'?'':m.unit==='ms'?'ms':m.unit==='req/s'?'/s':'' }}</span>
                    <span>{{ semoji(m.status) }}</span>
                  </div>
                </div>
                <div v-if="expandedMetric === m.key" class="bg-gray-50/50 rounded-lg p-2 mt-0.5 text-[9px] space-y-0.5 border border-gray-200">
                  <div><b>定义：</b>{{ m.description }}</div>
                  <div><b>计算：</b><code class="text-[8px] break-all">{{ m.formula }}</code></div>
                  <div><b>范围：</b>{{ m.range }} · {{ m.direction==='higher_better'?'优秀≥':'优秀≤' }}{{ m.threshold_good }} · {{ m.direction==='higher_better'?'正常≥':'正常≤' }}{{ m.threshold_ok }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 详情表 -->
        <div class="bg-white border rounded-xl overflow-hidden">
          <div class="p-3 bg-[#f8fafc] border-b text-[11px] font-bold text-[#64748b]">评测样本 ({{ report.items.length }}条)</div>
          <div class="overflow-x-auto max-h-[350px] overflow-y-auto">
            <table class="w-full text-[11px]">
              <thead class="sticky top-0 bg-[#f8fafc] text-[#94a3b8]"><tr><th class="p-2 text-left w-[150px]">问题</th><th class="p-2 w-[50px]">意图</th><th class="p-2 w-[55px]">最高分</th><th class="p-2 w-[40px]">引用</th><th class="p-2 w-[40px]">P@1</th><th class="p-2 w-[120px]">追问</th><th class="p-2 w-[55px]">延迟</th></tr></thead>
              <tbody>
                <tr v-for="item in report.items" :key="item.trace_id" class="border-t hover:bg-[#f8fafc]" :class="item.success?'':'bg-red-50'">
                  <td class="p-2 truncate max-w-[150px]" :title="item.question">{{ item.question }}</td>
                  <td class="p-2"><span class="px-1 py-0.5 rounded-full text-[8px] font-bold bg-blue-100 text-blue-600">{{ item.intent_label }}</span></td>
                  <td class="p-2 text-center font-mono font-bold" :class="item.top_score>=0.7?'text-green-600':item.top_score>=0.5?'text-amber-600':'text-red-500'">{{ item.top_score.toFixed(3) }}</td>
                  <td class="p-2 text-center">{{ item.citations_count }}</td>
                  <td class="p-2 text-center">{{ (item.scores||[])[0]>=0.7?'✓':'-' }}</td>
                  <td class="p-2 text-[9px] truncate max-w-[120px]">{{ (item.follow_ups||[]).slice(0,2).join(' / ') || '-' }}</td>
                  <td class="p-2 text-center font-mono">{{ item.latency_ms }}ms</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
      <div v-else-if="!loading" class="text-center py-16 text-[#94a3b8] text-[12px]">暂无评测数据</div>
    </div>
  </div>
</template>
