<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { authHeaders } from '../../api/auth'
import ListPagination from '../ListPagination.vue'
import ListQueryBar from '../ListQueryBar.vue'
import LogScrollDetail from './LogScrollDetail.vue'
import { defaultListQuery, toSearchParams, type ListQueryState } from '../../utils/listQuery'

export type LogKind = 'operation' | 'error' | 'api-call' | 'schedule'

const props = defineProps<{ kind: LogKind }>()

type LogRow = Record<string, unknown>

interface SqlItem {
  cmd_seq: number
  cmd_statement: string
  cmd_parameters: string
  cmd_table?: string
}

const rows = ref<LogRow[]>([])
const total = ref(0)
const loading = ref(false)
const query = ref<ListQueryState>(defaultListQuery(20))

const extraModule = ref('')
const extraClientIp = ref('')
const extraOperateNo = ref('')
const extraUserNo = ref('')
const extraErrorType = ref('')
const extraApiType = ref('')
const extraSuccess = ref('')
const extraExecuteState = ref('')
const extraTraceId = ref('')

const detailOpen = ref(false)
const detailLoading = ref(false)
const detailRow = ref<LogRow | null>(null)
const detailTab = ref<'detail' | 'sql'>('detail')
const sqlItems = ref<SqlItem[]>([])
const sqlTotal = ref(0)
const sqlLoading = ref(false)

const kindMeta = computed(() => {
  const map: Record<LogKind, { title: string; nameLabel: string; keywordPh: string }> = {
    operation: { title: '操作日志', nameLabel: '模块', keywordPh: 'URL / trace / 流水号 / 用户号' },
    error: { title: '异常日志', nameLabel: '模块', keywordPh: 'URL / trace / 异常信息' },
    'api-call': { title: 'API 调用日志', nameLabel: 'API 类型', keywordPh: '目标 URL / trace / 请求摘要' },
    schedule: { title: '定时任务日志', nameLabel: '任务名', keywordPh: '任务名 / 描述 / 错误信息' },
  }
  return map[props.kind]
})

const sortOptions = computed(() => {
  const base = [
    { value: 'created_at', label: '创建时间' },
    { value: 'log_id', label: '日志 ID' },
  ]
  if (props.kind === 'schedule') base.push({ value: 'start_time', label: '开始时间' })
  return base
})

const listColumns = computed(() => {
  switch (props.kind) {
    case 'operation':
      return [
        { key: 'client_ip', label: '客户端 IP' },
        { key: 'operate_desc', label: '操作描述', wide: true },
        { key: 'module', label: '模块' },
        { key: 'user_no', label: '操作人' },
        { key: 'time_consume_ms', label: '耗时(ms)' },
        { key: 'status', label: '状态', fmt: fmtOpStatus },
        { key: 'created_at', label: '操作时间', fmt: fmtDateTime },
      ]
    case 'error':
      return [
        { key: 'module', label: '模块' },
        { key: 'client_ip', label: '客户端 IP' },
        { key: 'error_type', label: '异常类型', fmt: fmtErrorType },
        { key: 'url', label: '请求 URL', wide: true },
        { key: 'error_message', label: '异常信息', wide: true },
        { key: 'created_at', label: '发生时间', fmt: fmtDateTime },
      ]
    case 'api-call':
      return [
        { key: 'api_type', label: 'API 类型', fmt: fmtApiType },
        { key: 'target_url', label: '目标 URL', wide: true },
        { key: 'method', label: '方法' },
        { key: 'status_code', label: '状态码' },
        { key: 'time_consume_ms', label: '耗时(ms)' },
        { key: 'success', label: '结果', fmt: fmtSuccess },
        { key: 'created_at', label: '调用时间', fmt: fmtDateTime },
      ]
    case 'schedule':
      return [
        { key: 'job_name', label: '任务名称' },
        { key: 'job_desc', label: '任务描述', wide: true },
        { key: 'job_info', label: '执行信息', wide: true },
        { key: 'error_msg', label: '错误信息', wide: true },
        { key: 'execute_state', label: '状态', fmt: fmtExecuteState },
        { key: 'created_at', label: '记录时间', fmt: fmtDateTime },
      ]
    default:
      return []
  }
})

const showSqlTab = computed(() => props.kind === 'operation')

function fmtDateTime(v: unknown): string {
  if (!v) return '-'
  const d = new Date(String(v))
  if (Number.isNaN(d.getTime())) return String(v)
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function fmtOpStatus(v: unknown): string {
  return Number(v) === 1 ? '成功' : '失败'
}

function fmtSuccess(v: unknown): string {
  return Number(v) === 1 ? '成功' : '失败'
}

function fmtExecuteState(v: unknown): string {
  return Number(v) === 1 ? '成功' : '失败'
}

function fmtErrorType(v: unknown): string {
  const map: Record<number, string> = { 1: '系统异常', 2: '操作异常', 3: 'API/集成异常' }
  return map[Number(v)] || String(v ?? '-')
}

function fmtApiType(v: unknown): string {
  const map: Record<string, string> = {
    inbound: '入站 HTTP',
    llm: 'LLM',
    rag: 'RAG',
    tool: '工具',
    mcp: 'MCP',
    embedding: '嵌入',
  }
  const s = String(v ?? '')
  return map[s] || s || '-'
}

function cellText(row: LogRow, col: { key: string; fmt?: (v: unknown) => string }): string {
  const raw = row[col.key]
  if (col.fmt) return col.fmt(raw)
  if (raw == null || raw === '') return '-'
  const s = String(raw)
  return s.length > 80 ? `${s.slice(0, 80)}…` : s
}

function buildExtras(): Record<string, string | undefined> {
  const e: Record<string, string | undefined> = {}
  if (props.kind === 'operation') {
    if (extraModule.value) e.module = extraModule.value
    if (extraClientIp.value) e.client_ip = extraClientIp.value
    if (extraOperateNo.value) e.operate_no = extraOperateNo.value
    if (extraUserNo.value) e.user_no = extraUserNo.value
  } else if (props.kind === 'error') {
    if (extraModule.value) e.module = extraModule.value
    if (extraClientIp.value) e.client_ip = extraClientIp.value
    if (extraOperateNo.value) e.operate_no = extraOperateNo.value
    if (extraErrorType.value) e.error_type = extraErrorType.value
  } else if (props.kind === 'api-call') {
    if (extraApiType.value) e.api_type = extraApiType.value
    if (extraSuccess.value !== '') e.success = extraSuccess.value
    if (extraTraceId.value) e.trace_id = extraTraceId.value
  } else if (props.kind === 'schedule') {
    if (extraModule.value) e.job_name = extraModule.value
    if (extraExecuteState.value !== '') e.execute_state = extraExecuteState.value
  }
  return e
}

function requestContentText(row: LogRow | null): string {
  if (!row) return ''
  const input = String(row.input_value || '').trim()
  if (input) return input
  const url = String(row.url || '')
  if (url) return `Method: GET\nURL: ${url}\n\n（历史记录未采集请求快照；新产生的异常日志将包含完整请求内容）`
  return '（无请求内容）'
}

async function loadList(): Promise<void> {
  loading.value = true
  try {
    const qs = toSearchParams(query.value, buildExtras())
    const res = await fetch(`/api/v1/admin/logs/${props.kind}?${qs}`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      rows.value = data.items || []
      total.value = data.total || 0
      if (data.page) query.value.page = data.page
      if (data.size) query.value.size = data.size
    }
  } finally {
    loading.value = false
  }
}

function resetQuery(): void {
  query.value = defaultListQuery(20)
  extraModule.value = ''
  extraClientIp.value = ''
  extraOperateNo.value = ''
  extraUserNo.value = ''
  extraErrorType.value = ''
  extraApiType.value = ''
  extraSuccess.value = ''
  extraExecuteState.value = ''
  extraTraceId.value = ''
  loadList()
}

async function loadSql(logId: number): Promise<void> {
  sqlLoading.value = true
  sqlItems.value = []
  sqlTotal.value = 0
  try {
    const res = await fetch(`/api/v1/admin/logs/operation/${logId}/sql`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      sqlItems.value = (data.items || []).map((it: Record<string, unknown>) => ({
        cmd_seq: Number(it.cmd_seq ?? it.cmdSeq ?? 0),
        cmd_statement: String(it.cmd_statement ?? it.cmdStatement ?? ''),
        cmd_parameters: String(it.cmd_parameters ?? it.cmdParameters ?? ''),
        cmd_table: String(it.cmd_table ?? it.cmdTable ?? ''),
      }))
      sqlTotal.value = Number(data.total ?? sqlItems.value.length)
    }
  } finally {
    sqlLoading.value = false
  }
}

async function openDetail(row: LogRow): Promise<void> {
  detailOpen.value = true
  detailTab.value = 'detail'
  detailRow.value = row
  detailLoading.value = true
  sqlItems.value = []
  try {
    const logId = row.log_id
    const res = await fetch(`/api/v1/admin/logs/${props.kind}/${logId}`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      detailRow.value = data.item || row
    }
    if (props.kind === 'operation' && row.log_id != null) {
      await loadSql(Number(row.log_id))
    }
  } finally {
    detailLoading.value = false
  }
}

async function switchDetailTab(tab: 'detail' | 'sql'): Promise<void> {
  if (detailTab.value === tab) return
  detailTab.value = tab
  if (tab === 'sql' && detailRow.value?.log_id != null && !sqlItems.value.length && !sqlLoading.value) {
    await loadSql(Number(detailRow.value.log_id))
  }
}

function closeDetail(): void {
  detailOpen.value = false
  detailRow.value = null
  detailTab.value = 'detail'
  sqlItems.value = []
}

watch(() => props.kind, () => {
  resetQuery()
})

watch(() => [query.value.page, query.value.size], loadList)

onMounted(loadList)
</script>

<template>
  <div class="log-mgmt">
    <div class="log-mgmt-card card">
      <div class="log-toolbar">
        <div>
          <h3 class="log-title">{{ kindMeta.title }}</h3>
          <p class="log-sub">运维日志（只读）· 共 <strong>{{ total }}</strong> 条</p>
        </div>
        <button type="button" class="haici-btn haici-btn--accent" :disabled="loading" @click="loadList">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
      </div>

      <div class="log-filters">
        <ListQueryBar
          v-model="query"
          :sort-options="sortOptions"
          :name-placeholder="kindMeta.nameLabel"
          :keyword-placeholder="kindMeta.keywordPh"
          @search="loadList"
          @reset="resetQuery"
        />
        <div class="log-extra-filters">
          <template v-if="kind === 'operation'">
            <label>客户端 IP <input v-model="extraClientIp" type="text" placeholder="模糊" @keyup.enter="query.page = 1; loadList()" /></label>
            <label>操作流水号 <input v-model="extraOperateNo" type="text" placeholder="模糊" @keyup.enter="query.page = 1; loadList()" /></label>
            <label>操作人 <input v-model="extraUserNo" type="text" placeholder="用户号" @keyup.enter="query.page = 1; loadList()" /></label>
            <label>模块 <input v-model="extraModule" type="text" placeholder="精确" @keyup.enter="query.page = 1; loadList()" /></label>
          </template>
          <template v-else-if="kind === 'error'">
            <label>客户端 IP <input v-model="extraClientIp" type="text" @keyup.enter="query.page = 1; loadList()" /></label>
            <label>操作流水号 <input v-model="extraOperateNo" type="text" @keyup.enter="query.page = 1; loadList()" /></label>
            <label>异常类型
              <select v-model="extraErrorType" @change="query.page = 1; loadList()">
                <option value="">全部</option>
                <option value="1">系统异常</option>
                <option value="2">操作异常</option>
                <option value="3">API/集成异常</option>
              </select>
            </label>
            <label>模块 <input v-model="extraModule" type="text" @keyup.enter="query.page = 1; loadList()" /></label>
          </template>
          <template v-else-if="kind === 'api-call'">
            <label>API 类型
              <select v-model="extraApiType" @change="query.page = 1; loadList()">
                <option value="">全部</option>
                <option value="inbound">入站 HTTP</option>
                <option value="llm">LLM</option>
                <option value="rag">RAG</option>
                <option value="tool">工具</option>
                <option value="mcp">MCP</option>
                <option value="embedding">嵌入</option>
              </select>
            </label>
            <label>结果
              <select v-model="extraSuccess" @change="query.page = 1; loadList()">
                <option value="">全部</option>
                <option value="1">成功</option>
                <option value="0">失败</option>
              </select>
            </label>
            <label>Trace ID <input v-model="extraTraceId" type="text" @keyup.enter="query.page = 1; loadList()" /></label>
          </template>
          <template v-else-if="kind === 'schedule'">
            <label>任务名 <input v-model="extraModule" type="text" @keyup.enter="query.page = 1; loadList()" /></label>
            <label>执行状态
              <select v-model="extraExecuteState" @change="query.page = 1; loadList()">
                <option value="">全部</option>
                <option value="1">成功</option>
                <option value="0">失败</option>
              </select>
            </label>
          </template>
        </div>
      </div>

      <div class="table-wrap">
        <table class="log-table">
          <thead>
            <tr>
              <th v-for="col in listColumns" :key="col.key" :class="{ wide: col.wide }">{{ col.label }}</th>
              <th class="col-action">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="String(row.log_id)">
              <td v-for="col in listColumns" :key="col.key" :class="{ wide: col.wide, mono: col.key.includes('url') || col.key === 'trace_id' }" :title="String(row[col.key] ?? '')">
                {{ cellText(row, col) }}
              </td>
              <td class="col-action">
                <button type="button" class="haici-btn haici-btn--accent haici-btn--sm" @click="openDetail(row)">详情</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!rows.length && !loading" class="empty">暂无日志</p>
      </div>
      <ListPagination v-model:page="query.page" v-model:size="query.size" :total="total" />
    </div>

    <!-- 详情抽屉 -->
    <div v-if="detailOpen" class="log-detail-mask" @click.self="closeDetail">
      <div class="log-detail-panel card">
        <div class="detail-hd">
          <div>
            <h3>{{ kindMeta.title }}详情 #{{ detailRow?.log_id }}</h3>
            <div v-if="showSqlTab" class="detail-tabs">
              <button type="button" :class="{ active: detailTab === 'detail' }" @click="switchDetailTab('detail')">详情</button>
              <button type="button" :class="{ active: detailTab === 'sql' }" @click="switchDetailTab('sql')">SQL</button>
            </div>
          </div>
          <button type="button" class="btn-close" @click="closeDetail">✕</button>
        </div>

        <p v-if="detailLoading" class="detail-loading">正在加载详情…</p>

        <!-- 操作日志 · 详情 -->
        <div v-else-if="kind === 'operation' && detailTab === 'detail'" class="detail-body">
          <section class="detail-section">
            <h4>基本信息</h4>
            <dl class="detail-dl">
              <div><dt>客户端 IP</dt><dd>{{ detailRow?.client_ip || '—' }}</dd></div>
              <div><dt>操作描述</dt><dd>{{ detailRow?.operate_desc || '—' }}</dd></div>
              <div><dt>模块</dt><dd>{{ detailRow?.module || '—' }}</dd></div>
              <div><dt>菜单权限</dt><dd class="mono">{{ detailRow?.menu_permission || '—' }}</dd></div>
              <div><dt>操作人</dt><dd>{{ detailRow?.user_no || '—' }} <span v-if="detailRow?.user_id" class="muted">(ID {{ detailRow.user_id }})</span></dd></div>
              <div><dt>操作流水号</dt><dd class="mono">{{ detailRow?.operate_no || '—' }}</dd></div>
              <div><dt>追踪 ID</dt><dd class="mono">{{ detailRow?.trace_id || '—' }}</dd></div>
              <div><dt>请求方法</dt><dd>{{ detailRow?.method || '—' }}</dd></div>
              <div><dt>耗时</dt><dd>{{ detailRow?.time_consume_ms ?? '—' }} ms</dd></div>
              <div><dt>状态</dt><dd>{{ fmtOpStatus(detailRow?.status) }}</dd></div>
              <div><dt>操作时间</dt><dd>{{ fmtDateTime(detailRow?.created_at) }}</dd></div>
            </dl>
          </section>
          <section class="detail-section">
            <h4>请求 URL</h4>
            <LogScrollDetail :value="String(detailRow?.url || '')" max-height="80px" />
          </section>
          <section class="detail-section">
            <h4>请求内容</h4>
            <LogScrollDetail :value="String(detailRow?.input_value || '')" />
          </section>
          <section class="detail-section">
            <h4>返回内容</h4>
            <LogScrollDetail :value="String(detailRow?.return_value || '')" />
          </section>
        </div>

        <!-- 操作日志 · SQL -->
        <div v-else-if="kind === 'operation' && detailTab === 'sql'" class="detail-body">
          <p v-if="sqlLoading" class="detail-loading">正在加载 SQL…</p>
          <template v-else-if="sqlItems.length">
            <p class="sql-summary">共 {{ sqlTotal }} 条 SQL 语句（按执行顺序）</p>
            <section v-for="item in sqlItems" :key="item.cmd_seq" class="detail-section">
              <h4>SQL [{{ item.cmd_seq }}]<span v-if="item.cmd_table" class="muted"> · {{ item.cmd_table }}</span></h4>
              <label class="field-label">语句</label>
              <LogScrollDetail :value="item.cmd_statement" />
              <label class="field-label">参数</label>
              <LogScrollDetail :value="item.cmd_parameters" />
            </section>
          </template>
          <div v-else class="sql-empty">
            <p>本次操作未采集到 SQL（可能无数据库访问，或仅为只读 GET 请求）</p>
          </div>
        </div>

        <!-- 异常日志 -->
        <div v-else-if="kind === 'error'" class="detail-body">
          <section class="detail-section">
            <h4>基本信息</h4>
            <dl class="detail-dl">
              <div><dt>模块</dt><dd>{{ detailRow?.module || '—' }}</dd></div>
              <div><dt>客户端 IP</dt><dd>{{ detailRow?.client_ip || '—' }}</dd></div>
              <div><dt>异常类型</dt><dd>{{ fmtErrorType(detailRow?.error_type) }}</dd></div>
              <div><dt>代码定位</dt><dd class="mono">{{ detailRow?.prog_impl || '—' }}</dd></div>
              <div><dt>操作流水号</dt><dd class="mono">{{ detailRow?.operate_no || '—' }}</dd></div>
              <div><dt>追踪 ID</dt><dd class="mono">{{ detailRow?.trace_id || '—' }}</dd></div>
              <div><dt>发生时间</dt><dd>{{ fmtDateTime(detailRow?.created_at) }}</dd></div>
            </dl>
          </section>
          <section class="detail-section">
            <h4>请求 URL</h4>
            <LogScrollDetail :value="String(detailRow?.url || '')" max-height="80px" />
          </section>
          <section class="detail-section">
            <h4>异常信息（完整堆栈 / 错误消息 / 响应体）</h4>
            <LogScrollDetail :value="String(detailRow?.error_message || '')" max-height="360px" />
          </section>
          <section class="detail-section">
            <h4>请求内容（方法 / URL / 头 / 请求体）</h4>
            <LogScrollDetail :value="requestContentText(detailRow)" max-height="280px" />
          </section>
        </div>

        <!-- API 调用日志 -->
        <div v-else-if="kind === 'api-call'" class="detail-body">
          <section class="detail-section">
            <h4>基本信息</h4>
            <dl class="detail-dl">
              <div><dt>API 类型</dt><dd>{{ fmtApiType(detailRow?.api_type) }}</dd></div>
              <div><dt>请求方法</dt><dd>{{ detailRow?.method || '—' }}</dd></div>
              <div><dt>状态码</dt><dd>{{ detailRow?.status_code ?? '—' }}</dd></div>
              <div><dt>结果</dt><dd>{{ fmtSuccess(detailRow?.success) }}</dd></div>
              <div><dt>耗时</dt><dd>{{ detailRow?.time_consume_ms ?? '—' }} ms</dd></div>
              <div><dt>用户 ID</dt><dd>{{ detailRow?.user_id ?? '—' }}</dd></div>
              <div><dt>追踪 ID</dt><dd class="mono">{{ detailRow?.trace_id || '—' }}</dd></div>
              <div><dt>调用时间</dt><dd>{{ fmtDateTime(detailRow?.created_at) }}</dd></div>
            </dl>
          </section>
          <section class="detail-section">
            <h4>目标 URL</h4>
            <LogScrollDetail :value="String(detailRow?.target_url || '')" max-height="80px" />
          </section>
          <section class="detail-section">
            <h4>请求摘要</h4>
            <LogScrollDetail :value="String(detailRow?.request_summary || '')" />
          </section>
          <section class="detail-section">
            <h4>响应摘要</h4>
            <LogScrollDetail :value="String(detailRow?.response_summary || '')" />
          </section>
          <section v-if="detailRow?.error_message" class="detail-section">
            <h4>错误信息</h4>
            <LogScrollDetail :value="String(detailRow.error_message)" />
          </section>
        </div>

        <!-- 定时任务日志 -->
        <div v-else-if="kind === 'schedule'" class="detail-body">
          <section class="detail-section">
            <h4>基本信息</h4>
            <dl class="detail-dl">
              <div><dt>任务名称</dt><dd>{{ detailRow?.job_name || '—' }}</dd></div>
              <div><dt>任务组</dt><dd>{{ detailRow?.job_group || '—' }}</dd></div>
              <div><dt>任务描述</dt><dd>{{ detailRow?.job_desc || '—' }}</dd></div>
              <div><dt>任务标签</dt><dd>{{ detailRow?.job_tag || '—' }}</dd></div>
              <div><dt>执行状态</dt><dd>{{ fmtExecuteState(detailRow?.execute_state) }}</dd></div>
              <div><dt>开始时间</dt><dd>{{ fmtDateTime(detailRow?.start_time) }}</dd></div>
              <div><dt>结束时间</dt><dd>{{ fmtDateTime(detailRow?.end_time) }}</dd></div>
              <div><dt>记录时间</dt><dd>{{ fmtDateTime(detailRow?.created_at) }}</dd></div>
            </dl>
          </section>
          <section class="detail-section">
            <h4>执行信息</h4>
            <LogScrollDetail :value="String(detailRow?.job_info || '')" />
          </section>
          <section v-if="detailRow?.error_msg" class="detail-section">
            <h4>错误信息</h4>
            <LogScrollDetail :value="String(detailRow.error_msg)" />
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-mgmt {
  flex: 1;
  min-height: 0;
  padding: 24px;
  overflow-y: auto;
}

.log-mgmt-card {
  max-width: 1200px;
  margin: 0 auto;
}

.log-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border-bottom: 1px solid #e2e8f0;
}

.log-title {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 800;
  color: #1e293b;
}

.log-sub {
  margin: 0;
  font-size: 12px;
  color: #64748b;
}

.log-filters {
  padding: 12px 18px;
  border-bottom: 1px solid #f1f5f9;
}

.log-extra-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  margin-top: 10px;
  font-size: 12px;
  color: #475569;
}

.log-extra-filters label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.log-extra-filters input,
.log-extra-filters select {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
}

.table-wrap {
  overflow-x: auto;
}

.log-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.log-table th,
.log-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid #f1f5f9;
}

.log-table th {
  background: #f8fafc;
  color: #64748b;
  font-weight: 700;
  white-space: nowrap;
}

.log-table td.wide,
.log-table th.wide {
  max-width: 220px;
}

.log-table td.mono {
  font-family: ui-monospace, monospace;
  font-size: 11px;
}

.col-action {
  white-space: nowrap;
  width: 72px;
}

.empty {
  padding: 32px;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
}

.haici-btn--sm {
  padding: 4px 10px;
  font-size: 11px;
}

/* 详情抽屉 */
.log-detail-mask {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  justify-content: flex-end;
}

.log-detail-panel {
  width: min(560px, 96vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  border-radius: 0;
  border-left: 1px solid #e2e8f0;
  background: #fff;
  box-shadow: -8px 0 32px rgba(15, 23, 42, 0.12);
}

.detail-hd {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.detail-hd h3 {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 800;
  color: #1e293b;
}

.detail-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  background: #f1f5f9;
  border-radius: 8px;
}

.detail-tabs button {
  border: none;
  background: transparent;
  padding: 5px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  cursor: pointer;
}

.detail-tabs button.active {
  background: #363e42;
  color: #fff;
}

.btn-close {
  border: none;
  background: #f1f5f9;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #64748b;
  flex-shrink: 0;
}

.detail-loading {
  padding: 24px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
}

.detail-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px 24px;
}

.detail-section {
  margin-bottom: 20px;
}

.detail-section h4 {
  margin: 0 0 10px;
  font-size: 12px;
  font-weight: 800;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.detail-dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

.detail-dl > div {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
}

.detail-dl dt {
  color: #94a3b8;
  font-weight: 700;
}

.detail-dl dd {
  margin: 0;
  color: #334155;
  word-break: break-all;
}

.detail-dl .mono {
  font-family: ui-monospace, monospace;
  font-size: 11px;
}

.muted {
  color: #94a3b8;
  font-weight: 400;
}

.field-label {
  display: block;
  margin: 8px 0 4px;
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
}

.sql-summary {
  margin: 0 0 12px;
  font-size: 12px;
  color: #64748b;
}

.sql-empty {
  padding: 32px 16px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}
</style>
