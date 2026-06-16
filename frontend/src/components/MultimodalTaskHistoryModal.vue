<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { authHeaders } from '../api/auth'
import { fixDisplayFilename } from '../utils/filename'

interface TaskItem {
  task_id: string
  filename: string
  status: string
  progress: number
  stage_label: string
  error?: string | null
  pipeline_stages: Record<string, { status: string; label: string; error?: string }>
  output_dir: string
  output_md: string
  output_manifest: string
  document_id: number | null
  created_at: string
  completed_at: string | null
  log_count: number
}
interface LogEntry { timestamp: string; level: string; message: string }

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; deleted: [] }>()

const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const statusFilter = ref<'all' | 'completed' | 'failed'>('all')
const keyword = ref('')
const selectedId = ref('')
const detailTask = ref<TaskItem | null>(null)
const detailLogs = ref<LogEntry[]>([])

const S_MAP: Record<string, string> = {
  pending: '等待',
  running: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}
const S_COLOR: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-600',
  running: 'bg-blue-100 text-blue-600',
  completed: 'bg-green-100 text-green-600',
  failed: 'bg-red-100 text-red-600',
  cancelled: 'bg-orange-100 text-orange-600',
}

const historyTasks = computed(() =>
  tasks.value.filter((t) => t.status === 'completed' || t.status === 'failed'),
)

const filteredTasks = computed(() => {
  let list = historyTasks.value
  if (statusFilter.value !== 'all') {
    list = list.filter((t) => t.status === statusFilter.value)
  }
  const kw = keyword.value.trim().toLowerCase()
  if (kw) {
    list = list.filter(
      (t) =>
        t.filename.toLowerCase().includes(kw) ||
        t.task_id.toLowerCase().includes(kw) ||
        (t.error || '').toLowerCase().includes(kw),
    )
  }
  return [...list].sort((a, b) => {
    const ta = new Date(a.completed_at || a.created_at).getTime()
    const tb = new Date(b.completed_at || b.created_at).getTime()
    return tb - ta
  })
})

const stats = computed(() => ({
  total: historyTasks.value.length,
  completed: historyTasks.value.filter((t) => t.status === 'completed').length,
  failed: historyTasks.value.filter((t) => t.status === 'failed').length,
}))

const displayName = (name: string) => fixDisplayFilename(name)

async function loadTasks() {
  loading.value = true
  try {
    const r = await fetch('/api/v1/multimodal-tasks?limit=100', { headers: authHeaders() })
    if (!r.ok) return
    const data = await r.json()
    tasks.value = (data.tasks || []).map((t: TaskItem) => ({
      ...t,
      filename: fixDisplayFilename(t.filename),
    }))
  } finally {
    loading.value = false
  }
}

async function openDetail(taskId: string) {
  selectedId.value = taskId
  const r = await fetch(`/api/v1/multimodal-tasks/${taskId}`, { headers: authHeaders() })
  if (!r.ok) return
  const d = await r.json()
  const task = d.task as TaskItem
  task.filename = fixDisplayFilename(task.filename)
  detailTask.value = task
  detailLogs.value = d.task.logs || []
}

async function deleteTask(taskId: string, status?: string) {
  const active = status === 'pending' || status === 'running'
  const msg = active
    ? '确定取消并删除该任务？正在处理的文档将停止入库。'
    : '确定删除该历史任务记录？'
  if (!confirm(msg)) return
  const r = await fetch(`/api/v1/multimodal-tasks/${taskId}`, { method: 'DELETE', headers: authHeaders() })
  if (!r.ok) {
    const d = await r.json().catch(() => ({}))
    alert(typeof d.detail === 'string' ? d.detail : '删除失败')
    return
  }
  if (selectedId.value === taskId) {
    selectedId.value = ''
    detailTask.value = null
    detailLogs.value = []
  }
  await loadTasks()
  emit('deleted')
}

function closeModal() {
  selectedId.value = ''
  detailTask.value = null
  detailLogs.value = []
  emit('close')
}

function fmt(s: string) {
  if (!s) return ''
  return new Date(s).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function fmtDateTime(s: string) {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

watch(
  () => props.open,
  (v) => {
    if (v) {
      loadTasks()
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="mm-history-overlay fixed inset-0 z-[200] flex items-center justify-center p-4 md:p-8"
      @keydown.esc="closeModal"
    >
      <div class="absolute inset-0 bg-[#0f172a]/45 backdrop-blur-[2px]" @click="closeModal" />

      <div
        class="mm-history-panel relative w-full max-w-[1280px] h-[min(92vh,880px)] bg-[#f8fafc] rounded-2xl shadow-2xl border border-[#e2e8f0] flex flex-col overflow-hidden"
        @click.stop
      >
        <!-- 顶栏 -->
        <div class="shrink-0 px-6 py-4 bg-white border-b flex items-center justify-between gap-4">
          <div>
            <h2 class="text-lg font-black text-[#1e293b]">多模态处理历史记录</h2>
            <p class="text-[11px] text-[#64748b] mt-0.5">
              共 {{ stats.total }} 条 · 成功 {{ stats.completed }} · 失败 {{ stats.failed }}
            </p>
          </div>
          <div class="flex items-center gap-2">
            <button
              class="text-[12px] px-3 py-1.5 rounded-lg border text-[#64748b] hover:bg-[#f1f5f9]"
              :disabled="loading"
              @click="loadTasks"
            >
              {{ loading ? '刷新中…' : '刷新' }}
            </button>
            <button
              class="w-8 h-8 rounded-lg border text-[#64748b] hover:bg-[#f1f5f9] text-lg leading-none"
              title="关闭"
              @click="closeModal"
            >
              ×
            </button>
          </div>
        </div>

        <!-- 筛选栏 -->
        <div class="shrink-0 px-6 py-3 bg-white border-b flex flex-wrap items-center gap-3">
          <div class="flex rounded-lg border overflow-hidden text-[12px] font-bold">
            <button
              class="px-4 py-1.5 transition-colors"
              :class="statusFilter === 'all' ? 'bg-[#363e42] text-white' : 'bg-white text-[#64748b] hover:bg-[#f8fafc]'"
              @click="statusFilter = 'all'"
            >
              全部 ({{ stats.total }})
            </button>
            <button
              class="px-4 py-1.5 border-l transition-colors"
              :class="statusFilter === 'completed' ? 'bg-green-600 text-white' : 'bg-white text-[#64748b] hover:bg-[#f8fafc]'"
              @click="statusFilter = 'completed'"
            >
              已完成 ({{ stats.completed }})
            </button>
            <button
              class="px-4 py-1.5 border-l transition-colors"
              :class="statusFilter === 'failed' ? 'bg-red-500 text-white' : 'bg-white text-[#64748b] hover:bg-[#f8fafc]'"
              @click="statusFilter = 'failed'"
            >
              失败 ({{ stats.failed }})
            </button>
          </div>
          <input
            v-model="keyword"
            type="text"
            class="flex-1 min-w-[200px] border rounded-lg px-3 py-1.5 text-[12px]"
            placeholder="搜索文件名 / 任务 ID / 错误信息"
          />
        </div>

        <!-- 主体：列表 + 详情 -->
        <div class="flex-1 min-h-0 grid gap-0" :class="selectedId ? 'grid-cols-1 lg:grid-cols-12' : 'grid-cols-1'">
          <!-- 列表 -->
          <div
            class="bg-white border-r flex flex-col min-h-0 overflow-hidden"
            :class="selectedId ? 'lg:col-span-5' : 'max-w-4xl mx-auto w-full'"
          >
            <div class="flex-1 overflow-y-auto">
              <table class="w-full text-[12px]">
                <thead class="bg-[#f8fafc] text-[#64748b] text-[11px] sticky top-0 z-10 border-b">
                  <tr>
                    <th class="p-3 text-left font-bold">文件名</th>
                    <th class="p-3 text-left font-bold w-20">状态</th>
                    <th v-if="!selectedId" class="p-3 text-left font-bold">阶段</th>
                    <th class="p-3 text-left font-bold w-36">完成时间</th>
                    <th class="p-3 text-left font-bold w-16">日志</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="t in filteredTasks"
                    :key="t.task_id"
                    class="border-b cursor-pointer transition-colors hover:bg-[#eff6ff]/60"
                    :class="selectedId === t.task_id ? 'bg-[#eff6ff]' : ''"
                    @click="openDetail(t.task_id)"
                  >
                    <td class="p-3">
                      <div class="font-bold text-[#1e293b] truncate max-w-[220px]" :title="displayName(t.filename)">
                        {{ displayName(t.filename) }}
                      </div>
                      <div class="text-[10px] text-[#94a3b8] font-mono mt-0.5">{{ t.task_id }}</div>
                    </td>
                    <td class="p-3">
                      <span class="text-[10px] px-2 py-0.5 rounded-full font-bold" :class="S_COLOR[t.status]">
                        {{ S_MAP[t.status] }}
                      </span>
                    </td>
                    <td v-if="!selectedId" class="p-3 text-[#64748b] max-w-[180px] truncate" :title="t.stage_label">
                      {{ t.status === 'failed' && t.error ? t.error.slice(0, 40) : t.stage_label }}
                    </td>
                    <td class="p-3 text-[11px] text-[#64748b] whitespace-nowrap">
                      {{ fmtDateTime(t.completed_at || t.created_at) }}
                    </td>
                    <td class="p-3 text-[11px] text-[#64748b]">{{ t.log_count }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-if="!filteredTasks.length" class="p-12 text-center text-[#94a3b8] text-sm">
                {{ loading ? '加载中…' : '暂无符合条件的历史记录' }}
              </p>
            </div>
          </div>

          <!-- 详情 -->
          <div v-if="selectedId && detailTask" class="lg:col-span-7 flex flex-col min-h-0 bg-white">
            <div class="shrink-0 px-5 py-4 border-b flex items-start justify-between gap-3">
              <div class="min-w-0">
                <h3 class="text-[15px] font-black truncate">{{ displayName(detailTask.filename) }}</h3>
                <p class="text-[11px] text-[#94a3b8] mt-1 font-mono">
                  {{ detailTask.task_id }} · {{ fmtDateTime(detailTask.created_at) }}
                  <span v-if="detailTask.completed_at"> → {{ fmtDateTime(detailTask.completed_at) }}</span>
                </p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span class="text-[10px] px-2 py-0.5 rounded-full font-bold" :class="S_COLOR[detailTask.status]">
                  {{ S_MAP[detailTask.status] }}
                </span>
                <button
                  class="text-[11px] text-red-500 hover:text-red-700 px-2 py-1 rounded border border-red-200"
                  @click="deleteTask(detailTask.task_id, detailTask.status)"
                >
                  删除
                </button>
              </div>
            </div>

            <div class="shrink-0 px-5 py-3 border-b">
              <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all"
                  :class="detailTask.status === 'failed' ? 'bg-red-400' : 'bg-green-400'"
                  :style="{ width: detailTask.progress + '%' }"
                />
              </div>
              <div class="flex justify-between text-[11px] mt-1.5 text-[#64748b]">
                <span class="font-bold">{{ detailTask.stage_label }}</span>
                <span class="font-mono font-bold">{{ detailTask.progress }}%</span>
              </div>
            </div>

            <div
              v-if="detailTask.error"
              class="shrink-0 mx-5 mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-[11px] text-red-600"
            >
              {{ detailTask.error }}
            </div>

            <div class="shrink-0 px-5 py-3 border-b">
              <div class="text-[10px] font-bold text-[#94a3b8] mb-2">处理阶段</div>
              <div class="flex gap-1 flex-wrap">
                <div
                  v-for="(v, k) in detailTask.pipeline_stages"
                  :key="k"
                  class="text-center text-[9px] py-1.5 px-1 rounded min-w-[52px] flex-1"
                  :class="
                    v.status === 'completed'
                      ? 'bg-green-50 text-green-700'
                      : v.status === 'in_progress'
                        ? 'bg-blue-50 text-blue-700 border border-blue-300'
                        : v.status === 'failed'
                          ? 'bg-red-50 text-red-600'
                          : 'bg-gray-50 text-gray-400'
                  "
                  :title="v.label"
                >
                  <div class="truncate">{{ v.label.slice(0, 10) }}</div>
                  <div>
                    {{
                      v.status === 'completed' ? '✓' : v.status === 'in_progress' ? '…' : v.status === 'failed' ? '✗' : ''
                    }}
                  </div>
                </div>
              </div>
            </div>

            <div v-if="detailTask.output_dir" class="shrink-0 px-5 py-2 border-b text-[11px]">
              <span class="font-bold text-[#64748b]">产物目录:</span>
              <code class="text-[10px] bg-[#f1f5f9] px-1.5 py-0.5 rounded ml-1">{{ detailTask.output_dir }}</code>
            </div>

            <div class="flex-1 overflow-y-auto p-5 min-h-0">
              <div class="text-[11px] font-bold text-[#64748b] mb-3">执行日志 · {{ detailLogs.length }} 条</div>
              <div v-if="!detailLogs.length" class="text-[12px] text-[#94a3b8] text-center py-10">暂无日志</div>
              <div
                v-for="(l, i) in detailLogs"
                :key="i"
                class="flex gap-3 text-[11px] py-1 font-mono border-b border-[#f1f5f9] last:border-0"
                :class="l.level === 'ERROR' ? 'text-red-500' : l.level === 'WARN' ? 'text-amber-500' : 'text-[#64748b]'"
              >
                <span class="text-[#94a3b8] shrink-0 w-14">{{ fmt(l.timestamp) }}</span>
                <span class="break-all leading-relaxed">{{ l.message }}</span>
              </div>
            </div>
          </div>

          <div
            v-else-if="filteredTasks.length"
            class="hidden lg:flex lg:col-span-7 items-center justify-center text-[#94a3b8] text-sm bg-white border-l"
          >
            点击左侧记录查看完整详情与日志
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.mm-history-overlay {
  animation: mm-fade-in 0.18s ease-out;
}
.mm-history-panel {
  animation: mm-slide-up 0.22s ease-out;
}
@keyframes mm-fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
@keyframes mm-slide-up {
  from {
    opacity: 0;
    transform: translateY(12px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
</style>
