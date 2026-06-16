<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { authHeaders, getAccessToken } from '../api/auth'
import { fixDisplayFilename } from '../utils/filename'
import MultimodalTaskHistoryModal from './MultimodalTaskHistoryModal.vue'

const uploadFiles = ref<File[]>([])
const uploadBusy = ref(false)
const uploadMsg = ref('')
const uploadMode = ref<'file' | 'text'>('file')
const textInput = ref('')

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

const tasks = ref<TaskItem[]>([])
const ACTIVE_TASK_LIMIT = 5
const showHistoryModal = ref(false)
const detailTaskId = ref('')
const detailTask = ref<TaskItem | null>(null)
const detailLogs = ref<LogEntry[]>([])
const esRef = ref<EventSource | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
let pollTimer: number | null = null

const canSubmitUpload = computed(
  () => !uploadBusy.value && (uploadFiles.value.length > 0 || textInput.value.trim().length > 0),
)

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

const displayName = (name: string) => fixDisplayFilename(name)

const isActiveStatus = (status: string) => status === 'pending' || status === 'running'
const isHistoryStatus = (status: string) => status === 'completed' || status === 'failed'

const activeTasks = computed(() =>
  tasks.value
    .filter((t) => isActiveStatus(t.status))
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, ACTIVE_TASK_LIMIT),
)

const historyCount = computed(() => tasks.value.filter((t) => isHistoryStatus(t.status)).length)

function onFileDrop(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer?.files) addFiles(e.dataTransfer.files)
}
function onFilePick(e: Event) {
  const t = e.target as HTMLInputElement
  if (t.files) addFiles(t.files)
  t.value = ''
}
function addFiles(fs: FileList) {
  for (let i = 0; i < fs.length; i++) uploadFiles.value.push(fs[i])
}
function removeFile(i: number) {
  uploadFiles.value.splice(i, 1)
}

async function startUpload() {
  if (!uploadFiles.value.length && !textInput.value.trim()) return
  uploadBusy.value = true
  uploadMsg.value = ''
  const submitted: string[] = []
  let lastTaskId = ''
  for (const f of uploadFiles.value) {
    const fd = new FormData()
    fd.append('file', f)
    fd.append('slice_method', 'auto')
    const r = await fetch('/api/v1/multimodal-tasks/upload', {
      method: 'POST',
      headers: { Authorization: `Bearer ${getAccessToken()}` },
      body: fd,
    })
    const d = await r.json().catch(() => ({}))
    if (r.ok && d.task_id) {
      submitted.push(f.name)
      lastTaskId = d.task_id
    } else {
      uploadMsg.value += `${f.name}: ${d.detail || '上传失败'}\n`
    }
  }
  if (textInput.value.trim()) {
    const blob = new Blob([textInput.value], { type: 'text/plain' })
    const fd = new FormData()
    fd.append('file', blob, 'pasted_text.txt')
    fd.append('slice_method', 'auto')
    const r = await fetch('/api/v1/multimodal-tasks/upload', {
      method: 'POST',
      headers: { Authorization: `Bearer ${getAccessToken()}` },
      body: fd,
    })
    const d = await r.json().catch(() => ({}))
    if (r.ok && d.task_id) {
      submitted.push('粘贴文本')
      lastTaskId = d.task_id
    } else {
      uploadMsg.value += `粘贴文本: ${d.detail || '上传失败'}\n`
    }
    textInput.value = ''
  }
  uploadFiles.value = []
  uploadBusy.value = false
  if (submitted.length) {
    uploadMsg.value =
      `已提交 ${submitted.length} 个任务，可在下方跟踪 MD 处理进度` +
      (uploadMsg.value ? '\n' + uploadMsg.value : '')
    await loadTasks()
    if (lastTaskId) {
      await selectTask(lastTaskId)
    }
  } else if (!uploadMsg.value) {
    uploadMsg.value = '提交失败，请重试'
  }
}

async function loadTasks() {
  try {
    const r = await fetch('/api/v1/multimodal-tasks?limit=50', { headers: authHeaders() })
    if (!r.ok) return
    const data = await r.json()
    tasks.value = (data.tasks || []).map((t: TaskItem) => ({
      ...t,
      filename: fixDisplayFilename(t.filename),
    }))
  } catch {
    /* ignore */
  }
}
async function loadDetail(taskId: string) {
  detailTaskId.value = taskId
  const r = await fetch(`/api/v1/multimodal-tasks/${taskId}`, { headers: authHeaders() })
  if (r.ok) {
    const d = await r.json()
    const task = d.task as TaskItem
    task.filename = fixDisplayFilename(task.filename)
    detailTask.value = task
    detailLogs.value = d.task.logs || []
  }
}
function connectSSE(taskId: string) {
  disconnectSSE()
  try {
    const es = new EventSource(
      `/api/v1/multimodal-tasks/${taskId}/logs?token=${encodeURIComponent(getAccessToken() || '')}`,
    )
    es.addEventListener('log', (e: MessageEvent) => {
      try {
        detailLogs.value.push(JSON.parse(e.data))
      } catch {
        /* ignore */
      }
    })
    es.addEventListener('progress', (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data)
        if (detailTask.value) {
          detailTask.value.progress = d.progress
          detailTask.value.status = d.status
          detailTask.value.stage_label = d.stage
          detailTask.value.pipeline_stages = d.pipeline_stages || detailTask.value.pipeline_stages
        }
      } catch {
        /* ignore */
      }
    })
    es.addEventListener('completed', () => {
      es.close()
      loadTasks()
    })
    es.addEventListener('failed', () => {
      es.close()
      loadTasks()
    })
    es.onerror = () => {
      es.close()
    }
    esRef.value = es
  } catch {
    /* ignore */
  }
}
function disconnectSSE() {
  esRef.value?.close()
  esRef.value = null
}
async function deleteTask(taskId: string, status?: string) {
  const active = status === 'pending' || status === 'running'
  const msg = active
    ? '确定取消并删除该任务？正在处理的文档将停止入库，已产生的中间产物会被清理。'
    : '确定删除该任务记录？'
  if (!confirm(msg)) return
  disconnectSSE()
  const r = await fetch(`/api/v1/multimodal-tasks/${taskId}`, { method: 'DELETE', headers: authHeaders() })
  if (!r.ok) {
    const d = await r.json().catch(() => ({}))
    alert(typeof d.detail === 'string' ? d.detail : '删除失败，请稍后重试')
    return
  }
  if (detailTaskId.value === taskId) {
    detailTaskId.value = ''
    detailTask.value = null
    detailLogs.value = []
  }
  await loadTasks()
}
function fmt(s: string) {
  if (!s) return ''
  return new Date(s).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
async function selectTask(taskId: string) {
  await loadDetail(taskId)
  const t = tasks.value.find((x) => x.task_id === taskId)
  if (t && isActiveStatus(t.status)) connectSSE(taskId)
  else disconnectSSE()
}

onMounted(() => {
  loadTasks()
  pollTimer = window.setInterval(loadTasks, 2000)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  disconnectSSE()
})
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto h-full">
    <div class="max-w-6xl mx-auto h-full flex flex-col">
      <div class="shrink-0 mb-4 bg-white border rounded-xl p-4">
        <div class="flex items-center gap-3 mb-3">
          <button
            class="text-[12px] font-bold px-3 py-1.5 rounded-lg"
            :class="uploadMode === 'file' ? 'bg-[#363e42] text-white' : 'border'"
            @click="uploadMode = 'file'"
          >
            上传文件
          </button>
          <button
            class="text-[12px] font-bold px-3 py-1.5 rounded-lg"
            :class="uploadMode === 'text' ? 'bg-[#363e42] text-white' : 'border'"
            @click="uploadMode = 'text'"
          >
            粘贴文本
          </button>
        </div>

        <div
          v-if="uploadMode === 'file'"
          class="border-2 border-dashed border-[#cbd5e1] rounded-xl p-6 text-center cursor-pointer hover:border-[#2563eb] transition-colors"
          @dragover.prevent
          @drop="onFileDrop"
          @click="fileInputRef?.click()"
        >
          <input
            ref="fileInputRef"
            type="file"
            multiple
            accept=".txt,.md,.pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.webp,.ppt,.pptx"
            class="hidden"
            @change="onFilePick"
          />
          <p class="text-[12px] text-[#64748b]">拖拽文件到此处，或点击选择</p>
          <p class="text-[10px] text-[#94a3b8] mt-1">支持 txt/md/pdf/office/图片（最多同时 6 个）</p>
        </div>
        <div v-else>
          <textarea
            v-model="textInput"
            rows="6"
            class="w-full border rounded-lg p-3 text-[12px] resize-y"
            placeholder="粘贴 Markdown 或文本内容..."
          />
        </div>

        <div v-if="uploadFiles.length" class="mt-3 flex flex-wrap gap-2">
          <div
            v-for="(f, i) in uploadFiles"
            :key="i"
            class="text-[11px] bg-[#f1f5f9] px-3 py-1.5 rounded-lg flex items-center gap-2"
          >
            {{ f.name }} <button class="text-red-400" @click="removeFile(i)">&times;</button>
          </div>
        </div>

        <div class="flex items-center gap-3 mt-3 flex-wrap">
          <button
            class="bg-[#2563eb] text-white px-5 py-2 rounded-lg font-bold text-[12px] disabled:opacity-50"
            :disabled="!canSubmitUpload"
            @click="startUpload"
          >
            {{ uploadBusy ? '提交中...' : '提交处理' }}
          </button>
          <span class="text-[11px] text-[#94a3b8]">上传后自动进入处理流水线，可在下方跟踪最新执行进度</span>
          <button
            class="ml-auto text-[12px] font-bold px-4 py-1.5 rounded-lg border border-[#cbd5e1] text-[#475569] hover:bg-[#f8fafc] hover:border-[#94a3b8] transition-colors flex items-center gap-2"
            @click="showHistoryModal = true"
          >
            <span>历史记录</span>
            <span
              v-if="historyCount"
              class="text-[10px] px-1.5 py-0.5 rounded-full bg-[#363e42] text-white min-w-[20px] text-center"
            >
              {{ historyCount }}
            </span>
          </button>
        </div>
        <p
          v-if="uploadMsg"
          class="text-[11px] mt-2 whitespace-pre-line"
          :class="uploadMsg.includes('失败') ? 'text-red-500' : 'text-green-600'"
        >
          {{ uploadMsg }}
        </p>
      </div>

      <div class="flex-1 grid grid-cols-5 gap-4 min-h-0">
        <div class="col-span-2 border rounded-xl overflow-hidden flex flex-col min-h-0">
          <!-- 正在执行 -->
          <div class="shrink-0 p-3 bg-[#f8fafc] border-b text-[11px] font-bold text-[#64748b] flex justify-between">
            <span>正在执行 ({{ activeTasks.length }})</span>
            <button class="text-[10px] text-[#2563eb]" @click="loadTasks">刷新</button>
          </div>
          <div class="flex-1 overflow-y-auto min-h-0">
            <div v-if="!activeTasks.length" class="p-8 text-center text-[#94a3b8] text-[12px]">
              暂无进行中的任务<br /><span class="text-[10px]">上传文件后将在此显示最新 {{ ACTIVE_TASK_LIMIT }} 条进度</span>
            </div>
            <div
              v-for="t in activeTasks"
              :key="t.task_id"
              class="border-b p-3 cursor-pointer transition-colors"
              :class="detailTaskId === t.task_id ? 'bg-[#eff6ff]' : 'hover:bg-[#f8fafc]'"
              @click="selectTask(t.task_id)"
            >
              <div class="flex items-center justify-between mb-1.5 gap-2">
                <span class="text-[12px] font-bold truncate flex-1 mr-2">{{ displayName(t.filename) }}</span>
                <div class="flex items-center gap-1 shrink-0">
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-bold" :class="S_COLOR[t.status]">{{
                    S_MAP[t.status]
                  }}</span>
                  <button
                    class="text-[10px] text-red-400 hover:text-red-600 px-1"
                    title="取消并删除"
                    @click.stop="deleteTask(t.task_id, t.status)"
                  >
                    删除
                  </button>
                </div>
              </div>
              <div class="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-1">
                <div
                  class="h-full rounded-full transition-all bg-blue-400"
                  :style="{ width: t.progress + '%' }"
                />
              </div>
              <div class="flex justify-between text-[10px] text-[#94a3b8]">
                <span class="truncate mr-2">{{ t.stage_label || '等待' }}</span><span class="font-mono">{{ t.progress }}%</span>
              </div>
            </div>
          </div>
        </div>

        <div class="col-span-3 border rounded-xl overflow-hidden flex flex-col">
          <template v-if="detailTask">
            <div class="p-3 bg-[#f8fafc] border-b flex items-center justify-between shrink-0">
              <div class="min-w-0 flex-1 mr-2">
                <div class="text-[13px] font-bold truncate">{{ displayName(detailTask.filename) }}</div>
                <div class="text-[10px] text-[#94a3b8]">
                  ID:{{ detailTask.task_id }} · {{ fmt(detailTask.created_at)
                  }}{{ detailTask.completed_at ? ' → ' + fmt(detailTask.completed_at) : '' }}
                </div>
              </div>
              <span
                class="text-[10px] px-1.5 py-0.5 rounded-full font-bold shrink-0 mr-2"
                :class="S_COLOR[detailTask.status]"
                >{{ S_MAP[detailTask.status] }}</span
              >
              <button class="text-[10px] text-red-400 hover:text-red-600" @click="deleteTask(detailTask.task_id, detailTask.status)">
                {{ detailTask.status === 'running' || detailTask.status === 'pending' ? '取消' : '删除' }}
              </button>
            </div>
            <div class="px-4 py-3 shrink-0">
              <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all"
                  :class="
                    detailTask.status === 'failed'
                      ? 'bg-red-400'
                      : detailTask.status === 'cancelled'
                        ? 'bg-orange-400'
                      : detailTask.status === 'completed'
                        ? 'bg-green-400'
                        : 'bg-blue-400'
                  "
                  :style="{ width: detailTask.progress + '%' }"
                />
              </div>
              <div class="flex justify-between text-[11px] mt-1.5">
                <span class="font-bold text-[#64748b]">{{ detailTask.stage_label }}</span
                ><span class="font-bold font-mono">{{ detailTask.progress }}%</span>
              </div>
            </div>
            <div
              v-if="detailTask.error"
              class="px-4 py-2 mx-4 mb-2 bg-red-50 border border-red-200 rounded-lg text-[11px] text-red-600 shrink-0"
            >
              {{ detailTask.error }}
            </div>
            <div class="px-4 py-2 border-b shrink-0">
              <div class="text-[10px] font-bold text-[#94a3b8] mb-1.5">处理阶段</div>
              <div class="flex gap-1">
                <div
                  v-for="(v, k) in detailTask.pipeline_stages"
                  :key="k"
                  class="flex-1 text-center text-[9px] py-1.5 rounded transition-colors"
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
                  <div class="truncate">{{ v.label.slice(0, 8) }}</div>
                  <div>
                    {{
                      v.status === 'completed' ? '✓' : v.status === 'in_progress' ? '…' : v.status === 'failed' ? '✗' : ''
                    }}
                  </div>
                </div>
              </div>
            </div>
            <div v-if="detailTask.output_dir" class="px-4 py-2 border-b text-[11px] shrink-0">
              <span class="font-bold text-[#64748b]">产物:</span>
              <code class="text-[10px] bg-[#f1f5f9] px-1.5 py-0.5 rounded ml-1">{{ detailTask.output_dir }}</code>
            </div>
            <div
              v-if="detailTask.status === 'completed'"
              class="px-4 py-2 text-[10px] text-[#94a3b8] shrink-0"
            >
              中间产物: normalized.md / manifest.json → 知识库管理页查看
            </div>
            <div class="flex-1 overflow-y-auto p-3 min-h-0">
              <div class="text-[10px] font-bold text-[#94a3b8] mb-2">
                执行日志{{ detailTask.status === 'running' ? ' (实时)' : '' }} · {{ detailLogs.length }} 条
              </div>
              <div v-if="!detailLogs.length" class="text-[11px] text-[#94a3b8] text-center py-8">暂无日志</div>
              <div
                v-for="(l, i) in detailLogs"
                :key="i"
                class="flex gap-2 text-[11px] py-0.5 font-mono"
                :class="l.level === 'ERROR' ? 'text-red-500' : l.level === 'WARN' ? 'text-amber-500' : 'text-[#64748b]'"
              >
                <span class="text-[#94a3b8] shrink-0 w-[52px]">{{ fmt(l.timestamp) }}</span>
                <span class="break-all">{{ l.message }}</span>
              </div>
            </div>
          </template>
          <div v-else class="flex-1 flex items-center justify-center text-[#94a3b8] text-[12px]">
            点击左侧正在执行的任务查看详情和实时日志
          </div>
        </div>
      </div>

      <MultimodalTaskHistoryModal
        :open="showHistoryModal"
        @close="showHistoryModal = false"
        @deleted="loadTasks"
      />
    </div>
  </div>
</template>
