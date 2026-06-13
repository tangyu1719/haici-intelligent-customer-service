<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { authHeaders, getAccessToken } from '../api/auth'

interface TaskItem {
  task_id: string; filename: string; status: string
  progress: number; stage_label: string; error?: string|null
  pipeline_stages: Record<string,{status:string;label:string;error?:string}>
  output_dir: string; output_md: string; output_manifest: string
  document_id: number|null; created_at: string; completed_at: string|null
  log_count: number
}
interface LogEntry { timestamp: string; level: string; message: string }

const tasks = ref<TaskItem[]>([])
const detailTaskId = ref('')
const detailTask = ref<TaskItem|null>(null)
const detailLogs = ref<LogEntry[]>([])
const msg = ref('')
const esRef = ref<EventSource|null>(null)
let pollTimer: number|null = null

const S_MAP: Record<string,string> = { pending:'等待', running:'处理中', completed:'已完成', failed:'失败' }
const S_COLOR: Record<string,string> = { pending:'bg-gray-100 text-gray-600', running:'bg-blue-100 text-blue-600', completed:'bg-green-100 text-green-600', failed:'bg-red-100 text-red-600' }

async function loadTasks() {
  try {
    const r = await fetch('/api/v1/multimodal-tasks?limit=50', { headers: authHeaders() })
    if (r.ok) tasks.value = (await r.json()).tasks || []
  } catch { /* ignore */ }
}
async function loadDetail(taskId: string) {
  detailTaskId.value = taskId
  const r = await fetch(`/api/v1/multimodal-tasks/${taskId}`, { headers: authHeaders() })
  if (r.ok) {
    const d = await r.json()
    detailTask.value = d.task
    detailLogs.value = d.task.logs || []
  }
}
function connectSSE(taskId: string) {
  disconnectSSE()
  try {
    const es = new EventSource(`/api/v1/multimodal-tasks/${taskId}/logs?token=${encodeURIComponent(getAccessToken()||'')}`)
    es.addEventListener('log', (e: MessageEvent) => { try { detailLogs.value.push(JSON.parse(e.data)) } catch { /* */ } })
    es.addEventListener('progress', (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data)
        if (detailTask.value) {
          detailTask.value.progress = d.progress; detailTask.value.status = d.status
          detailTask.value.stage_label = d.stage; detailTask.value.pipeline_stages = d.pipeline_stages || detailTask.value.pipeline_stages
        }
      } catch { /* */ }
    })
    es.addEventListener('completed', () => { es.close(); loadTasks() })
    es.addEventListener('failed', () => { es.close(); loadTasks() })
    es.onerror = () => { es.close() }
    esRef.value = es
  } catch { /* */ }
}
function disconnectSSE() { esRef.value?.close(); esRef.value = null }
async function deleteTask(taskId: string) {
  if (!confirm('删除任务记录？')) return
  await fetch(`/api/v1/multimodal-tasks/${taskId}`, { method:'DELETE', headers:authHeaders() })
  if (detailTaskId.value === taskId) { detailTaskId.value = ''; detailTask.value = null; detailLogs.value = [] }
  await loadTasks()
}
function fmt(s: string) { if(!s)return''; return new Date(s).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}) }

onMounted(() => { loadTasks(); pollTimer = window.setInterval(loadTasks, 2000) })
onUnmounted(() => { if(pollTimer) clearInterval(pollTimer); disconnectSSE() })
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto h-full">
    <div class="max-w-6xl mx-auto h-full flex flex-col">
      <div class="shrink-0 mb-4">
        <h2 class="text-lg font-black">多模态文档处理</h2>
        <p class="text-[11px] text-[#64748b]">上传文档后自动进入处理流水线。每个文件独立追踪进度、阶段和中间产物。每2秒自动刷新状态。</p>
        <p v-if="msg" class="text-[12px] mt-1" :class="msg.includes('失败')?'text-red-500':'text-green-600'">{{ msg }}</p>
      </div>

      <div class="flex-1 grid grid-cols-5 gap-4 min-h-0">
        <!-- 左侧任务列表 -->
        <div class="col-span-2 border rounded-xl overflow-hidden flex flex-col">
          <div class="p-3 bg-[#f8fafc] border-b text-[11px] font-bold text-[#64748b] flex justify-between shrink-0">
            <span>处理任务 ({{ tasks.length }})</span>
            <button class="text-[10px] text-[#2563eb]" @click="loadTasks">刷新</button>
          </div>
          <div class="flex-1 overflow-y-auto">
            <div v-if="!tasks.length" class="p-8 text-center text-[#94a3b8] text-[12px]">暂无处理任务<br><span class="text-[10px]">在知识库管理页面上传文档后自动创建</span></div>
            <div v-for="t in tasks" :key="t.task_id"
              class="border-b p-3 cursor-pointer transition-colors"
              :class="detailTaskId===t.task_id?'bg-[#eff6ff]':'hover:bg-[#f8fafc]'"
              @click="loadDetail(t.task_id); connectSSE(t.task_id)"
            >
              <div class="flex items-center justify-between mb-1.5">
                <span class="text-[12px] font-bold truncate flex-1 mr-2">{{ t.filename }}</span>
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-bold shrink-0" :class="S_COLOR[t.status]">{{ S_MAP[t.status] }}</span>
              </div>
              <div class="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-1">
                <div class="h-full rounded-full transition-all duration-500"
                  :class="t.status==='failed'?'bg-red-400':t.status==='completed'?'bg-green-400':'bg-blue-400'"
                  :style="{width:t.progress+'%'}"
                ></div>
              </div>
              <div class="flex justify-between text-[10px] text-[#94a3b8]">
                <span class="truncate mr-2">{{ t.stage_label || '等待开始' }}</span>
                <span class="font-mono">{{ t.progress }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 右侧任务详情 -->
        <div class="col-span-3 border rounded-xl overflow-hidden flex flex-col">
          <template v-if="detailTask">
            <!-- 头部 -->
            <div class="p-3 bg-[#f8fafc] border-b flex items-center justify-between shrink-0">
              <div class="min-w-0 flex-1 mr-2">
                <div class="text-[13px] font-bold truncate">{{ detailTask.filename }}</div>
                <div class="text-[10px] text-[#94a3b8]">ID: {{ detailTask.task_id }} · 创建: {{ fmt(detailTask.created_at) }}{{ detailTask.completed_at?' · 完成: '+fmt(detailTask.completed_at):'' }}</div>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-bold" :class="S_COLOR[detailTask.status]">{{ S_MAP[detailTask.status] }}</span>
                <button class="text-[10px] text-red-400 hover:text-red-600" @click="deleteTask(detailTask.task_id)">删除</button>
              </div>
            </div>
            <!-- 进度条 -->
            <div class="px-4 py-3 shrink-0">
              <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div class="h-full rounded-full transition-all duration-300"
                  :class="detailTask.status==='failed'?'bg-red-400':detailTask.status==='completed'?'bg-green-400':'bg-blue-400'"
                  :style="{width:detailTask.progress+'%'}"
                ></div>
              </div>
              <div class="flex justify-between text-[11px] mt-1.5">
                <span class="font-bold text-[#64748b]">{{ detailTask.stage_label }}</span>
                <span class="font-bold font-mono">{{ detailTask.progress }}%</span>
              </div>
            </div>
            <!-- 错误信息 -->
            <div v-if="detailTask.error" class="px-4 py-2 mx-4 mb-2 bg-red-50 border border-red-200 rounded-lg text-[11px] text-red-600 shrink-0">{{ detailTask.error }}</div>
            <!-- 处理阶段 -->
            <div class="px-4 py-2 border-b shrink-0">
              <div class="text-[10px] font-bold text-[#94a3b8] mb-1.5">处理阶段</div>
              <div class="flex gap-1">
                <div v-for="(v,k) in detailTask.pipeline_stages" :key="k"
                  class="flex-1 text-center text-[9px] py-1.5 px-0.5 rounded transition-colors"
                  :class="v.status==='completed'?'bg-green-50 text-green-700':v.status==='in_progress'?'bg-blue-50 text-blue-700 border border-blue-300':v.status==='failed'?'bg-red-50 text-red-600':'bg-gray-50 text-gray-400'"
                  :title="v.label"
                >
                  <div class="truncate">{{ v.label.slice(0,8) }}</div>
                  <div class="mt-0.5">{{ v.status==='completed'?'✓':v.status==='in_progress'?'●':v.status==='failed'?'✗':'' }}</div>
                </div>
              </div>
            </div>
            <!-- 输出产物 -->
            <div v-if="detailTask.output_dir" class="px-4 py-2 border-b text-[11px] shrink-0">
              <span class="font-bold text-[#64748b]">输出目录:</span>
              <code class="text-[10px] bg-[#f1f5f9] px-1.5 py-0.5 rounded ml-1">{{ detailTask.output_dir }}</code>
              <span v-if="detailTask.output_manifest" class="ml-3">
                <span class="font-bold text-[#64748b]">Manifest:</span>
                <code class="text-[10px] bg-[#f1f5f9] px-1.5 py-0.5 rounded ml-1">{{ detailTask.output_manifest }}</code>
              </span>
            </div>
            <!-- 中间产物提示 -->
            <div v-if="detailTask.status==='completed'" class="px-4 py-2 text-[10px] text-[#94a3b8] shrink-0">
              中间产物: normalized.md / normalized.txt / manifest.json → 可在知识库管理页查看
            </div>
            <!-- 日志 -->
            <div class="flex-1 overflow-y-auto p-3 min-h-0">
              <div class="text-[10px] font-bold text-[#94a3b8] mb-2">处理日志{{ detailTask.status==='running'?' (实时更新)':'' }} — {{ detailLogs.length }}条</div>
              <div v-if="!detailLogs.length" class="text-[11px] text-[#94a3b8] text-center py-8">暂无日志</div>
              <div v-for="(l,i) in detailLogs" :key="i" class="flex gap-2 text-[11px] py-0.5 font-mono leading-relaxed"
                :class="l.level==='ERROR'?'text-red-500':l.level==='WARN'?'text-amber-500':'text-[#64748b]'"
              >
                <span class="text-[#94a3b8] shrink-0 w-[52px]">{{ fmt(l.timestamp) }}</span>
                <span class="break-all">{{ l.message }}</span>
              </div>
            </div>
          </template>
          <div v-else class="flex-1 flex items-center justify-center text-[#94a3b8] text-[12px]">点击左侧任务查看详情和实时日志</div>
        </div>
      </div>
    </div>
  </div>
</template>
