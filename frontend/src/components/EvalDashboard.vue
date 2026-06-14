<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'
import SimpleLineChart from './charts/SimpleLineChart.vue'

interface RagItem {
  trace_id: string; question: string; answer_preview: string
  intent_label: string; rewritten_query: string; rag_query: string
  citations_count: number; top_score: number; avg_score: number
  scores: number[]
  pass_at_1: number; pass_at_3: number; pass_at_5: number
  faithfulness: number|null; answer_relevancy: number|null
  context_precision: number|null; context_recall: number|null
  anti_dilution: boolean; kb_id: number|null
  llm_provider: string; llm_model: string
  answer_length: number; follow_ups: string[]; follow_ups_count: number; total_tokens: number
  time_consume_ms: number; span_intent_ms: number; span_rewrite_ms: number
  span_retrieval_ms: number; span_generation_ms: number
  success: boolean; created_at: string
}
interface RagReport {
  total: number; success_count: number; fail_rate: number
  avg_top_score: number; avg_citations: number; avg_latency_ms: number
  pass_at_1: number; pass_at_3: number; pass_at_5: number
  avg_faithfulness: number; avg_answer_relevancy: number
  avg_context_precision: number; avg_context_recall: number
  score_distribution: Record<string,number>
  intent_distribution: Record<string,number>
  anti_dilution_count: number
  items: RagItem[]; generated_at: string
}

interface EvalOverview {
  period_days: number; generated_at: string
  summary: { call_count:number;fail_count:number;fail_rate:number;avg_rtt_ms:number;total_tokens:number }
  by_type: Record<string,{call_count:number;fail_rate:number;avg_rtt_ms:number;total_tokens:number}>
  daily_trend: {date:string;call_count:number}[]
}

const TYPE_LABELS: Record<string,string> = { llm:'LLM调用', rag:'RAG检索', tool:'工具', mcp:'MCP', embedding:'嵌入' }
const days = ref(7)
const tab = ref<'overview'|'rag'>('rag')
const loading = ref(false)
const overview = ref<EvalOverview|null>(null)
const ragReport = ref<RagReport|null>(null)

const pct = (v:number|null|undefined):string => v==null?'—':(v*100).toFixed(1)+'%'
const num = (v:number|null|undefined):string => v==null?'—':String(v)

const trendPoints = computed(() => (overview.value?.daily_trend||[]).map(d=>({label:d.date,value:d.call_count})))

async function loadOverview() {
  const r = await fetch(`/api/v1/admin/eval/overview?days=${days.value}`, { headers:authHeaders() })
  if(r.ok) overview.value = await r.json()
}
async function loadRag() {
  loading.value = true
  try {
    const r = await fetch(`/api/v1/admin/eval/rag-metrics?limit=50&days=${days.value}`, { headers:authHeaders() })
    if(r.ok) ragReport.value = await r.json()
  } finally { loading.value = false }
}
async function refresh() { await Promise.all([loadOverview(), loadRag()]) }

onMounted(refresh)
</script>

<template>
  <div class="p-6 overflow-y-auto h-full">
    <div class="max-w-7xl mx-auto">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-lg font-black">EVAL 评测</h2>
          <p class="text-[11px] text-[#64748b]">RAGAS风格指标 · Pass@K · Span追踪 · 分数分布</p>
        </div>
        <div class="flex items-center gap-3">
          <label class="text-[11px] text-[#64748b]">周期
            <select v-model.number="days" class="border rounded px-2 py-1 text-[11px] ml-1" @change="refresh">
              <option :value="7">7天</option><option :value="14">14天</option><option :value="30">30天</option>
            </select>
          </label>
          <button class="text-[11px] font-bold px-3 py-1 rounded border" @click="refresh">刷新</button>
        </div>
      </div>

      <!-- Tab切换 -->
      <div class="flex gap-0 mb-4 border-b">
        <button class="px-4 py-2 text-[12px] font-bold border-b-2 transition-colors"
          :class="tab==='overview'?'border-[#2563eb] text-[#1d4ed8]':'border-transparent text-[#64748b]'"
          @click="tab='overview'">总览</button>
        <button class="px-4 py-2 text-[12px] font-bold border-b-2 transition-colors"
          :class="tab==='rag'?'border-[#2563eb] text-[#1d4ed8]':'border-transparent text-[#64748b]'"
          @click="tab='rag';loadRag()">RAG 评测</button>
      </div>

      <!-- ═══ 总览 ═══ -->
      <div v-if="tab==='overview'">
        <div v-if="overview" class="grid grid-cols-5 gap-3 mb-4">
          <div v-for="t in overview.types.filter((t:string)=>overview!.by_type[t]?.call_count>0)" :key="t"
            class="bg-white border rounded-xl p-3">
            <div class="text-[10px] font-bold text-[#64748b] mb-1">{{ TYPE_LABELS[t]||t }}</div>
            <div class="text-[20px] font-black text-[#363e42]">{{ overview.by_type[t]?.call_count||0 }}</div>
            <div class="text-[10px] text-[#94a3b8]">失败{{ pct(overview.by_type[t]?.fail_rate) }} · {{ num(overview.by_type[t]?.avg_rtt_ms) }}ms</div>
          </div>
        </div>
        <div v-if="overview?.daily_trend?.length" class="bg-white border rounded-xl p-4">
          <h3 class="text-[12px] font-bold mb-2">每日调用趋势</h3>
          <SimpleLineChart :points="trendPoints" :width="700" color="#3b82f6" />
        </div>
        <p v-if="!overview" class="text-center text-[#94a3b8] text-[12px] py-8">暂无EVAL数据，发起对话后自动写入</p>
      </div>

      <!-- ═══ RAG评测 ═══ -->
      <div v-if="tab==='rag'">
        <!-- RAGAS 指标卡片 -->
        <div v-if="ragReport" class="grid grid-cols-4 gap-3 mb-4">
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8] font-bold">Pass@1</div>
            <div class="text-[24px] font-black" :class="ragReport.pass_at_1>=0.8?'text-green-500':ragReport.pass_at_1>=0.5?'text-amber-500':'text-red-400'">{{ (ragReport.pass_at_1*100).toFixed(0) }}%</div>
            <div class="text-[9px] text-[#94a3b8]">top_score≥0.7</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8] font-bold">Pass@3</div>
            <div class="text-[24px] font-black" :class="ragReport.pass_at_3>=0.9?'text-green-500':ragReport.pass_at_3>=0.6?'text-amber-500':'text-red-400'">{{ (ragReport.pass_at_3*100).toFixed(0) }}%</div>
            <div class="text-[9px] text-[#94a3b8]">Top3有≥0.5分</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8] font-bold">Pass@5</div>
            <div class="text-[24px] font-black" :class="ragReport.pass_at_5>=0.95?'text-green-500':ragReport.pass_at_5>=0.7?'text-amber-500':'text-red-400'">{{ (ragReport.pass_at_5*100).toFixed(0) }}%</div>
            <div class="text-[9px] text-[#94a3b8]">Top5有≥0.35分</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8] font-bold">平均最高分</div>
            <div class="text-[24px] font-black text-[#2563eb]">{{ ragReport.avg_top_score.toFixed(3) }}</div>
            <div class="text-[9px] text-[#94a3b8]">avg_citations: {{ ragReport.avg_citations }}</div>
          </div>
        </div>

        <!-- 次行指标 -->
        <div v-if="ragReport" class="grid grid-cols-4 gap-3 mb-4">
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8] font-bold">忠实度 Faithfulness</div>
            <div class="text-[18px] font-black" :class="ragReport.avg_faithfulness>=0.9?'text-green-500':'text-amber-500'">{{ ragReport.avg_faithfulness>0?(ragReport.avg_faithfulness*100).toFixed(0)+'%':'待评测' }}</div>
            <div class="text-[9px] text-[#94a3b8]">LLM-as-Judge</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8] font-bold">答案相关性 Relevancy</div>
            <div class="text-[18px] font-black" :class="ragReport.avg_answer_relevancy>=0.85?'text-green-500':'text-amber-500'">{{ ragReport.avg_answer_relevancy>0?(ragReport.avg_answer_relevancy*100).toFixed(0)+'%':'待评测' }}</div>
            <div class="text-[9px] text-[#94a3b8]">LLM-as-Judge</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8] font-bold">上下文精度 Precision</div>
            <div class="text-[18px] font-black text-[#2563eb]">{{ ragReport.avg_context_precision>0?(ragReport.avg_context_precision*100).toFixed(0)+'%':'待评测' }}</div>
            <div class="text-[9px] text-[#94a3b8]">检索信噪比</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8] font-bold">上下文召回率 Recall</div>
            <div class="text-[18px] font-black text-[#2563eb]">{{ ragReport.avg_context_recall>0?(ragReport.avg_context_recall*100).toFixed(0)+'%':'待评测' }}</div>
            <div class="text-[9px] text-[#94a3b8]">检索覆盖度</div>
          </div>
        </div>

        <!-- 分数分布 + 意图分布 -->
        <div v-if="ragReport" class="grid grid-cols-2 gap-4 mb-4">
          <div class="bg-white border rounded-xl p-4">
            <h3 class="text-[11px] font-bold text-[#64748b] mb-2">检索分数分布</h3>
            <div class="space-y-1">
              <div v-for="(count,range) in ragReport.score_distribution" :key="range" class="flex items-center gap-2 text-[11px]">
                <span class="w-16 text-right text-[#94a3b8]">{{ range }}</span>
                <div class="flex-1 h-4 bg-gray-100 rounded-full overflow-hidden">
                  <div class="h-full bg-blue-400 rounded-full" :style="{width:ragReport.total?(count/ragReport.total*100)+'%':'0%'}"></div>
                </div>
                <span class="w-8 font-bold">{{ count }}</span>
              </div>
            </div>
          </div>
          <div class="bg-white border rounded-xl p-4">
            <h3 class="text-[11px] font-bold text-[#64748b] mb-2">意图分布</h3>
            <div class="space-y-1">
              <div v-for="(count,intent) in ragReport.intent_distribution" :key="intent" class="flex items-center gap-2 text-[11px]">
                <span class="w-20 text-right truncate text-[#94a3b8]">{{ intent }}</span>
                <div class="flex-1 h-4 bg-gray-100 rounded-full overflow-hidden">
                  <div class="h-full bg-amber-400 rounded-full" :style="{width:ragReport.total?(count/ragReport.total*100)+'%':'0%'}"></div>
                </div>
                <span class="w-8 font-bold">{{ count }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 详细列表 -->
        <div v-if="ragReport?.items?.length" class="bg-white border rounded-xl overflow-hidden">
          <div class="p-3 bg-[#f8fafc] border-b text-[11px] font-bold text-[#64748b]">
            RAG对话详情 ({{ ragReport.items.length }}条) · 平均延迟{{ ragReport.avg_latency_ms }}ms
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-[11px]">
              <thead class="bg-[#f8fafc] text-[#94a3b8]">
                <tr>
                  <th class="p-2 text-left w-[180px]">问题</th>
                  <th class="p-2 text-left w-[60px]">意图</th>
                  <th class="p-2 text-left w-[140px]">改写Query</th>
                  <th class="p-2 text-center w-[50px]">引用</th>
                  <th class="p-2 text-center w-[55px]">最高分</th>
                  <th class="p-2 text-center w-[55px]">P@1</th>
                  <th class="p-2 text-center w-[55px]">P@3</th>
                  <th class="p-2 text-left w-[160px]">追问建议</th>
                  <th class="p-2 text-center w-[55px]">字数</th>
                  <th class="p-2 text-center w-[55px]">延迟ms</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in ragReport.items" :key="item.trace_id" class="border-t hover:bg-[#f8fafc]"
                  :class="item.success?'':'bg-red-50'">
                  <td class="p-2 truncate max-w-[180px]" :title="item.question">{{ item.question }}</td>
                  <td class="p-2"><span class="px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-blue-100 text-blue-600">{{ item.intent_label }}</span></td>
                  <td class="p-2 truncate max-w-[140px] text-[#64748b]" :title="item.rewritten_query">{{ item.rewritten_query }}</td>
                  <td class="p-2 text-center font-mono">{{ item.citations_count }}</td>
                  <td class="p-2 text-center font-mono font-bold" :class="item.top_score>=0.7?'text-green-600':item.top_score>=0.5?'text-amber-600':'text-red-500'">{{ item.top_score.toFixed(3) }}</td>
                  <td class="p-2 text-center">{{ item.pass_at_1?'✓':'-' }}</td>
                  <td class="p-2 text-center">{{ item.pass_at_3?'✓':'-' }}</td>
                  <td class="p-2 text-[10px] text-[#64748b] truncate max-w-[160px]" :title="(item.follow_ups||[]).join(' | ')">
                    <span v-if="(item.follow_ups||[]).length">{{ (item.follow_ups||[]).slice(0,2).join(' / ') }}</span>
                    <span v-else class="text-[#94a3b8]">-</span>
                  </td>
                  <td class="p-2 text-center font-mono">{{ item.answer_length }}</td>
                  <td class="p-2 text-center font-mono">{{ item.time_consume_ms }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <p v-if="!loading && !ragReport?.items?.length" class="text-center text-[#94a3b8] text-[12px] py-8">
          暂无RAG评测数据。发起RAG对话后自动记录指标。
        </p>
        <p v-if="loading" class="text-center text-[#94a3b8] text-[12px] py-4">加载中...</p>
      </div>
    </div>
  </div>
</template>
