<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface MetricItem {
  key: string; name: string; layer: string
  description: string; formula: string; range: string
  threshold_ok: number; threshold_good: number
  direction: string; unit: string
  value: number; status: string; display_value: string
}
interface LayerData { label: string; description: string; metrics: MetricItem[] }
interface PipelineStage { id: string; label: string; icon: string }
interface RagItem {
  trace_id: string; question: string; intent_label: string
  rewritten_query: string; top_score: number; scores: number[]
  citations_count: number; answer_length: number; latency_ms: number
  follow_ups: string[]; success: boolean; created_at: string
}
interface FullReport {
  total: number; success_count: number; fail_count: number
  period_days: number; generated_at: string
  pipeline_stages: PipelineStage[]
  layer1_retrieval: LayerData & { pass_at_1: number; pass_at_3: number; pass_at_5: number }
  layer2_generation: LayerData
  layer3_system: LayerData
  items: RagItem[]
}

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

const statusEmoji = (s: string) => ({ good: '🟢', ok: '🟡', warn: '🔴' } as Record<string, string>)[s] || '⚪'
const statusLabel = (s: string) => ({ good: '优秀', ok: '正常', warn: '需优化' } as Record<string, string>)[s] || s

onMounted(load)
</script>

<template>
  <div class="p-6 overflow-y-auto h-full">
    <div class="max-w-7xl mx-auto">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-lg font-black">RAG 评测报告</h2>
          <p class="text-[11px] text-[#64748b]">三层指标体系 · 管道可视化 · 每指标含定义/公式/阈值</p>
        </div>
        <div class="flex items-center gap-3">
          <label class="text-[11px] text-[#64748b]">周期
            <select v-model.number="days" class="border rounded px-2 py-1 text-[11px] ml-1" @change="load">
              <option :value="7">7天</option><option :value="14">14天</option><option :value="30">30天</option>
            </select>
          </label>
          <button class="text-[11px] font-bold px-3 py-1 rounded border" :disabled="loading" @click="load">刷新</button>
        </div>
      </div>

      <div v-if="loading" class="text-center py-16 text-[#94a3b8]">加载中...</div>

      <template v-if="report">
        <!-- 汇总卡片 -->
        <div class="grid grid-cols-5 gap-3 mb-4">
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8]">评测样本</div>
            <div class="text-[24px] font-black text-[#363e42]">{{ report.total }}</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8]">成功率</div>
            <div class="text-[24px] font-black text-green-500">{{ ((report.success_count/report.total)*100).toFixed(0) }}%</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8]">Pass@1</div>
            <div class="text-[24px] font-black text-[#2563eb]">{{ (report.layer1_retrieval.pass_at_1*100).toFixed(0) }}%</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8]">Pass@3</div>
            <div class="text-[24px] font-black text-[#2563eb]">{{ (report.layer1_retrieval.pass_at_3*100).toFixed(0) }}%</div>
          </div>
          <div class="bg-white border rounded-xl p-3 text-center">
            <div class="text-[10px] text-[#94a3b8]">Pass@5</div>
            <div class="text-[24px] font-black text-[#2563eb]">{{ (report.layer1_retrieval.pass_at_5*100).toFixed(0) }}%</div>
          </div>
        </div>

        <!-- 管道可视化 -->
        <div class="bg-white border rounded-xl p-4 mb-4">
          <h3 class="text-[12px] font-bold mb-3">RAG 管道</h3>
          <div class="flex items-center gap-2 flex-wrap">
            <template v-for="(stage, idx) in report.pipeline_stages" :key="stage.id">
              <div class="flex flex-col items-center">
                <div class="w-10 h-10 rounded-full border-2 flex items-center justify-center text-lg"
                  :class="idx <= 4 ? 'border-blue-300 bg-blue-50' : idx <= 6 ? 'border-green-300 bg-green-50' : 'border-amber-300 bg-amber-50'">
                  {{ stage.icon }}
                </div>
                <span class="text-[9px] mt-1 text-[#64748b]">{{ stage.label }}</span>
              </div>
              <span v-if="idx < report.pipeline_stages.length - 1" class="text-[#cbd5e1] text-lg">→</span>
            </template>
          </div>
          <div class="flex justify-between mt-2 text-[9px] text-[#94a3b8]">
            <span>检索阶段</span>
            <span>生成阶段</span>
            <span>输出阶段</span>
          </div>
        </div>

        <!-- 三层指标 -->
        <div class="grid grid-cols-3 gap-4 mb-4">
          <!-- 第一层：检索质量 -->
          <div class="bg-white border rounded-xl p-4">
            <div class="flex items-center gap-2 mb-3 pb-2 border-b">
              <span class="text-lg">🔍</span>
              <div>
                <h3 class="text-[12px] font-bold">{{ report.layer1_retrieval.label }}</h3>
                <p class="text-[9px] text-[#94a3b8]">{{ report.layer1_retrieval.description }}</p>
              </div>
            </div>
            <div class="space-y-2">
              <div v-for="m in report.layer1_retrieval.metrics" :key="m.key">
                <div class="flex items-center justify-between text-[11px] cursor-pointer hover:bg-[#f8fafc] rounded px-1 py-0.5"
                  @click="expandedMetric = expandedMetric === m.key ? null : m.key">
                  <span class="font-bold">{{ m.name }}</span>
                  <span class="font-mono font-bold" :class="m.status==='warn'?'text-red-500':m.status==='good'?'text-green-500':'text-amber-500'">{{ m.display_value }}</span>
                </div>
                <div v-if="expandedMetric === m.key" class="bg-[#f8fafc] rounded-lg p-2 text-[10px] space-y-1 mb-1">
                  <div><b>定义：</b>{{ m.description }}</div>
                  <div><b>公式：</b><code class="text-[9px]">{{ m.formula }}</code></div>
                  <div><b>范围：</b>{{ m.range }} | 优秀≥{{ m.threshold_good }} | 正常≥{{ m.threshold_ok }}</div>
                  <div><b>当前状态：</b>{{ statusEmoji(m.status) }} {{ statusLabel(m.status) }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 第二层：生成一致性 -->
          <div class="bg-white border rounded-xl p-4">
            <div class="flex items-center gap-2 mb-3 pb-2 border-b">
              <span class="text-lg">🤖</span>
              <div>
                <h3 class="text-[12px] font-bold">{{ report.layer2_generation.label }}</h3>
                <p class="text-[9px] text-[#94a3b8]">{{ report.layer2_generation.description }}</p>
              </div>
            </div>
            <div class="space-y-2">
              <div v-for="m in report.layer2_generation.metrics" :key="m.key">
                <div class="flex items-center justify-between text-[11px] cursor-pointer hover:bg-[#f8fafc] rounded px-1 py-0.5"
                  @click="expandedMetric = expandedMetric === m.key ? null : m.key">
                  <span class="font-bold">{{ m.name }}</span>
                  <span class="font-mono font-bold" :class="m.value===0?'text-[#94a3b8]':m.status==='warn'?'text-red-500':m.status==='good'?'text-green-500':'text-amber-500'">{{ m.value > 0 ? m.display_value : '待评测' }}</span>
                </div>
                <div v-if="expandedMetric === m.key" class="bg-[#f8fafc] rounded-lg p-2 text-[10px] space-y-1 mb-1">
                  <div><b>定义：</b>{{ m.description }}</div>
                  <div><b>公式：</b><code class="text-[9px]">{{ m.formula }}</code></div>
                  <div><b>范围：</b>{{ m.range }} | 优秀≥{{ m.threshold_good }} | 正常≥{{ m.threshold_ok }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 第三层：系统工程 -->
          <div class="bg-white border rounded-xl p-4">
            <div class="flex items-center gap-2 mb-3 pb-2 border-b">
              <span class="text-lg">⚙️</span>
              <div>
                <h3 class="text-[12px] font-bold">{{ report.layer3_system.label }}</h3>
                <p class="text-[9px] text-[#94a3b8]">{{ report.layer3_system.description }}</p>
              </div>
            </div>
            <div class="space-y-2">
              <div v-for="m in report.layer3_system.metrics" :key="m.key">
                <div class="flex items-center justify-between text-[11px] cursor-pointer hover:bg-[#f8fafc] rounded px-1 py-0.5"
                  @click="expandedMetric = expandedMetric === m.key ? null : m.key">
                  <span class="font-bold">{{ m.name }}</span>
                  <span class="font-mono font-bold" :class="m.status==='warn'?'text-red-500':m.status==='good'?'text-green-500':'text-amber-500'">{{ m.display_value }}{{ m.unit === 'ms' ? 'ms' : m.unit === 'req/s' ? '/s' : '' }}</span>
                </div>
                <div v-if="expandedMetric === m.key" class="bg-[#f8fafc] rounded-lg p-2 text-[10px] space-y-1 mb-1">
                  <div><b>定义：</b>{{ m.description }}</div>
                  <div><b>公式：</b><code class="text-[9px]">{{ m.formula }}</code></div>
                  <div><b>范围：</b>{{ m.range }} | 优秀≤{{ m.threshold_good }}{{ m.unit }} | 正常≤{{ m.threshold_ok }}{{ m.unit }}</div>
                  <div><b>当前状态：</b>{{ statusEmoji(m.status) }} {{ statusLabel(m.status) }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 评测详情表 -->
        <div class="bg-white border rounded-xl overflow-hidden">
          <div class="p-3 bg-[#f8fafc] border-b text-[11px] font-bold text-[#64748b]">
            评测样本详情 ({{ report.items.length }}条)
          </div>
          <div class="overflow-x-auto max-h-[400px] overflow-y-auto">
            <table class="w-full text-[11px]">
              <thead class="sticky top-0 bg-[#f8fafc] text-[#94a3b8]">
                <tr>
                  <th class="p-2 text-left w-[140px]">问题</th>
                  <th class="p-2 w-[50px]">意图</th>
                  <th class="p-2 w-[55px]">最高分</th>
                  <th class="p-2 w-[45px]">引用</th>
                  <th class="p-2 w-[45px]">P@1</th>
                  <th class="p-2 w-[100px]">追问</th>
                  <th class="p-2 w-[55px]">延迟</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in report.items" :key="item.trace_id" class="border-t hover:bg-[#f8fafc]" :class="item.success?'':'bg-red-50'">
                  <td class="p-2 truncate max-w-[140px]" :title="item.question">{{ item.question }}</td>
                  <td class="p-2"><span class="px-1 py-0.5 rounded-full text-[8px] font-bold bg-blue-100 text-blue-600">{{ item.intent_label }}</span></td>
                  <td class="p-2 text-center font-mono font-bold" :class="item.top_score>=0.7?'text-green-600':item.top_score>=0.5?'text-amber-600':'text-red-500'">{{ item.top_score.toFixed(3) }}</td>
                  <td class="p-2 text-center">{{ item.citations_count }}</td>
                  <td class="p-2 text-center">{{ item.scores[0]>=0.7?'✓':'-' }}</td>
                  <td class="p-2 text-[9px] truncate max-w-[100px]">{{ (item.follow_ups||[]).slice(0,2).join(' / ') || '-' }}</td>
                  <td class="p-2 text-center font-mono">{{ item.latency_ms }}ms</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <div v-else-if="!loading" class="text-center py-16 text-[#94a3b8] text-[12px]">暂无评测数据，发起RAG对话后自动记录</div>
    </div>
  </div>
</template>
