<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { authHeaders } from '../api/auth'

interface AgentGuide {
  role?: string
  trigger?: string
  pipeline?: string
  impact?: string
  risks?: string[]
  can_edit?: string[]
  must_not_edit?: string[]
  variable_docs?: Record<string, string>
  rollback?: string
  warning?: string
  related_files?: string[]
}

interface AgentCatalogItem {
  agent_key: string
  label: string
  group: string
  kind: string
  hint?: string
  variables?: string[]
  has_override?: boolean
  builtin_exists?: boolean
  guide?: AgentGuide
  is_sub_agent?: boolean
  parent_key?: string
  overview_only?: boolean
}

const loading = ref(false)
const msg = ref('')
const catalog = ref<AgentCatalogItem[]>([])
const selectedKey = ref('')
const activeGroup = ref('')
const mdContent = ref('')
const selectedGuide = ref<AgentGuide>({})
const overviewOnly = ref(false)
const guideExpanded = ref(true)

const GROUP_LABELS: Record<string, string> = {
  multimodal_image_vlm: 'VLM 图片',
  multimodal_image_ocr: 'OCR + LLM',
  doc_normalize: '文档标准化',
  chat_agent: 'AI 问答运维',
  other: '其他',
}

const GROUP_DESC: Record<string, string> = {
  multimodal_image_vlm: '知识库入库：VLM 分类 + 按类型生成图片描述（改此处影响新上传文档）',
  multimodal_image_ocr: 'VLM 不可用时的 OCR + LLM 降级描述路径',
  doc_normalize: '文档清洗、结构化与摘要生成',
  chat_agent: '问答编排与运维诊断（部分 Agent 尚未接入主链路）',
}

const GROUP_ORDER = ['multimodal_image_vlm', 'multimodal_image_ocr', 'chat_agent', 'doc_normalize', 'other']

const KIND_LABELS: Record<string, string> = {
  vlm: 'VLM',
  llm: 'LLM',
}

/** VLM Tab 内芯片排序：总览 → 分类 → 各描述模板 */
const VLM_CHIP_ORDER = [
  'vlm_image_agent',
  'image_type_classifier_agent',
  'image_describe_ui_menu_agent',
  'image_describe_ui_design_agent',
  'image_describe_flowchart_agent',
  'image_describe_chart_agent',
  'image_describe_api_diagram_agent',
  'image_describe_general_agent',
]

function resolveGroupKey(a: AgentCatalogItem): string {
  let gk = a.group || 'other'
  if (gk === 'multimodal_image') {
    gk = a.kind === 'vlm' ? 'multimodal_image_vlm' : 'multimodal_image_ocr'
  }
  return gk
}

const groupedAgents = computed(() => {
  const m: Record<string, AgentCatalogItem[]> = {}
  for (const a of catalog.value) {
    const gk = resolveGroupKey(a)
    if (!m[gk]) m[gk] = []
    m[gk].push(a)
  }
  for (const gk of Object.keys(m)) {
    if (gk === 'multimodal_image_vlm') {
      m[gk].sort((a, b) => {
        const ia = VLM_CHIP_ORDER.indexOf(a.agent_key)
        const ib = VLM_CHIP_ORDER.indexOf(b.agent_key)
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
      })
    } else {
      m[gk].sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
    }
  }
  return m
})

const sortedGroupKeys = computed(() => {
  const keys = Object.keys(groupedAgents.value)
  return [...keys].sort((a, b) => {
    const ia = GROUP_ORDER.indexOf(a)
    const ib = GROUP_ORDER.indexOf(b)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  })
})

const agentsInGroup = computed(() => groupedAgents.value[activeGroup.value] || [])

const selectedMeta = computed(() => catalog.value.find((a) => a.agent_key === selectedKey.value))

const activeGuide = computed<AgentGuide>(() => {
  const fromMeta = selectedMeta.value?.guide
  if (fromMeta && Object.keys(fromMeta).length) return fromMeta
  return selectedGuide.value
})

const msgIsError = computed(() => msg.value.includes('失败'))

const canEditPrompt = computed(() => !overviewOnly.value)

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
    selectedGuide.value = d.guide || {}
    overviewOnly.value = Boolean(d.overview_only)
    const meta = catalog.value.find((a) => a.agent_key === key)
    if (meta) activeGroup.value = resolveGroupKey(meta)
  } catch (e: unknown) {
    msg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function switchGroup(gk: string) {
  activeGroup.value = gk
  const items = groupedAgents.value[gk] || []
  if (!items.length) return
  if (!items.some((a) => a.agent_key === selectedKey.value)) {
    const firstEditable = items.find((a) => !a.overview_only) || items[0]
    void loadMd(firstEditable.agent_key)
  }
}

async function saveMd() {
  if (!selectedKey.value || !canEditPrompt.value) return
  loading.value = true
  msg.value = ''
  try {
    const r = await fetch(`/api/v1/settings/agents-md/${encodeURIComponent(selectedKey.value)}`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: mdContent.value }),
    })
    if (!r.ok) throw new Error('保存失败')
    msg.value = 'Prompt 已保存，重启后端后对新请求生效'
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

watch(sortedGroupKeys, (keys) => {
  if (!activeGroup.value && keys.length) activeGroup.value = keys[0]
})

onMounted(async () => {
  loading.value = true
  try {
    await loadCatalog()
    if (catalog.value.length) {
      const vlm = catalog.value.find((a) => a.agent_key === 'image_type_classifier_agent')
      const first = vlm || catalog.value.find((a) => !a.overview_only) || catalog.value[0]
      activeGroup.value = resolveGroupKey(first)
      await loadMd(first.agent_key)
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="agent-config-page">
    <header class="agent-page-header">
      <div class="agent-page-header-main">
        <h2 class="agent-page-title">Agent 配置</h2>
        <p class="agent-page-desc">
          编辑各 Agent 的 <code>AGENT.md</code> Prompt 模板。保存后写入
          <code>backend/data/agent_config.json</code> 与对应
          <code>backend/data/agents/{agent_key}/AGENT.md</code>，<strong>需重启后端</strong>后生效；仅影响后续新入库文档或未来接入的链路。
          <router-link to="/admin/agent-gateway" class="agent-gateway-link">添加/管理 LLM 模型节点请前往 Agent 网关 → 模型连接</router-link>
        </p>
      </div>
      <div v-if="msg" class="agent-page-toast" :class="msgIsError ? 'is-error' : 'is-success'">
        {{ msg }}
      </div>
    </header>

    <div class="agent-global-alert">
      <strong>改前必读：</strong>
      每个 Agent 在下方「运维说明」中标注了系统职责、触发时机与误改后果。
      请勿删除 <code>{变量}</code> 占位符、JSON 输出约束等硬规则；不确定时先备份当前内容或从 Git 恢复。
    </div>

    <div class="agent-picker">
      <div class="agent-group-tabs" role="tablist">
        <button
          v-for="gk in sortedGroupKeys"
          :key="gk"
          type="button"
          role="tab"
          class="agent-group-tab"
          :class="{ active: activeGroup === gk }"
          :aria-selected="activeGroup === gk"
          @click="switchGroup(gk)"
        >
          {{ GROUP_LABELS[gk] || gk }}
          <span class="agent-group-tab-count">{{ groupedAgents[gk]?.length || 0 }}</span>
        </button>
      </div>
      <p v-if="activeGroup && GROUP_DESC[activeGroup]" class="agent-group-desc">
        {{ GROUP_DESC[activeGroup] }}
      </p>
      <div class="agent-chip-row">
        <button
          v-for="a in agentsInGroup"
          :key="a.agent_key"
          type="button"
          class="agent-chip"
          :class="{
            active: selectedKey === a.agent_key,
            'agent-chip--overview': a.overview_only,
            'agent-chip--sub': a.is_sub_agent,
          }"
          @click="loadMd(a.agent_key)"
        >
          <span class="agent-chip-label">{{ a.label }}</span>
          <span class="agent-chip-tags">
            <span v-if="a.overview_only" class="agent-tag agent-tag--info">说明</span>
            <span v-else class="agent-tag" :class="a.kind === 'vlm' ? 'agent-tag--vlm' : 'agent-tag--llm'">
              {{ KIND_LABELS[a.kind] || a.kind }}
            </span>
            <span v-if="a.has_override" class="agent-tag agent-tag--dirty">已改</span>
          </span>
        </button>
      </div>
    </div>

    <section class="agent-editor">
      <template v-if="selectedMeta">
        <div class="agent-editor-header">
          <div class="agent-editor-title-row">
            <h3 class="agent-editor-title">{{ selectedMeta.label }}</h3>
            <span
              v-if="!selectedMeta.overview_only"
              class="agent-tag agent-tag--lg"
              :class="selectedMeta.kind === 'vlm' ? 'agent-tag--vlm' : 'agent-tag--llm'"
            >
              {{ KIND_LABELS[selectedMeta.kind] || selectedMeta.kind }}
            </span>
            <span v-if="selectedMeta.overview_only" class="agent-tag agent-tag--info agent-tag--lg">仅说明</span>
            <span v-if="selectedMeta.is_sub_agent" class="agent-tag agent-tag--sub agent-tag--lg">子 Agent</span>
            <span v-if="selectedMeta.has_override" class="agent-tag agent-tag--dirty agent-tag--lg">已修改</span>
          </div>
          <p v-if="selectedMeta.hint" class="agent-editor-hint">{{ selectedMeta.hint }}</p>

          <!-- 运维说明 -->
          <div v-if="activeGuide.role || activeGuide.warning" class="agent-guide">
            <button type="button" class="agent-guide-toggle" @click="guideExpanded = !guideExpanded">
              <span class="agent-guide-toggle-title">运维说明 — 改什么、不能改什么</span>
              <span class="agent-guide-toggle-icon">{{ guideExpanded ? '收起' : '展开' }}</span>
            </button>
            <div v-show="guideExpanded" class="agent-guide-body">
              <div v-if="activeGuide.warning" class="agent-guide-warning">
                {{ activeGuide.warning }}
              </div>
              <div class="agent-guide-grid">
                <div v-if="activeGuide.role" class="agent-guide-block">
                  <h4 class="agent-guide-h">系统职责</h4>
                  <p>{{ activeGuide.role }}</p>
                </div>
                <div v-if="activeGuide.pipeline" class="agent-guide-block">
                  <h4 class="agent-guide-h">调用链路</h4>
                  <p>{{ activeGuide.pipeline }}</p>
                </div>
                <div v-if="activeGuide.trigger" class="agent-guide-block">
                  <h4 class="agent-guide-h">何时触发</h4>
                  <p>{{ activeGuide.trigger }}</p>
                </div>
                <div v-if="activeGuide.impact" class="agent-guide-block">
                  <h4 class="agent-guide-h">影响范围</h4>
                  <p>{{ activeGuide.impact }}</p>
                </div>
              </div>
              <div v-if="activeGuide.risks?.length" class="agent-guide-block agent-guide-block--full">
                <h4 class="agent-guide-h agent-guide-h--risk">误改后果</h4>
                <ul class="agent-guide-list">
                  <li v-for="(r, i) in activeGuide.risks" :key="'r' + i">{{ r }}</li>
                </ul>
              </div>
              <div class="agent-guide-columns">
                <div v-if="activeGuide.can_edit?.length" class="agent-guide-block">
                  <h4 class="agent-guide-h agent-guide-h--ok">可以改</h4>
                  <ul class="agent-guide-list">
                    <li v-for="(c, i) in activeGuide.can_edit" :key="'c' + i">{{ c }}</li>
                  </ul>
                </div>
                <div v-if="activeGuide.must_not_edit?.length" class="agent-guide-block">
                  <h4 class="agent-guide-h agent-guide-h--no">禁止改</h4>
                  <ul class="agent-guide-list">
                    <li v-for="(m, i) in activeGuide.must_not_edit" :key="'m' + i">{{ m }}</li>
                  </ul>
                </div>
              </div>
              <div
                v-if="activeGuide.variable_docs && Object.keys(activeGuide.variable_docs).length"
                class="agent-guide-block agent-guide-block--full"
              >
                <h4 class="agent-guide-h">模板变量含义</h4>
                <dl class="agent-var-docs">
                  <template v-for="(desc, vname) in activeGuide.variable_docs" :key="vname">
                    <dt><code>{{ braceVar(String(vname)) }}</code></dt>
                    <dd>{{ desc }}</dd>
                  </template>
                </dl>
              </div>
              <div v-if="activeGuide.rollback" class="agent-guide-block agent-guide-block--full agent-guide-rollback">
                <h4 class="agent-guide-h">回滚方式</h4>
                <p>{{ activeGuide.rollback }}</p>
              </div>
              <div v-if="activeGuide.related_files?.length" class="agent-guide-related">
                <span class="agent-guide-related-k">相关代码</span>
                <code v-for="(f, i) in activeGuide.related_files" :key="'f' + i" class="agent-guide-related-v">{{ f }}</code>
              </div>
            </div>
          </div>

          <div class="agent-meta-bar">
            <div class="agent-meta-item">
              <span class="agent-meta-k">Agent Key</span>
              <code class="agent-meta-v">{{ selectedMeta.agent_key }}</code>
            </div>
            <div v-if="selectedMeta.variables?.length" class="agent-meta-item agent-meta-item--vars">
              <span class="agent-meta-k">模板变量</span>
              <div class="agent-var-list">
                <code v-for="v in selectedMeta.variables" :key="v" class="agent-var-chip">{{ braceVar(v) }}</code>
              </div>
            </div>
          </div>
        </div>

        <div class="agent-editor-body">
          <div class="agent-editor-toolbar">
            <span class="agent-editor-file">
              <template v-if="overviewOnly">本项为链路说明，请在上方芯片选择具体子 Agent 编辑 Prompt</template>
              <template v-else>AGENT.md · ## Prompt 段（系统执行时提取此段）</template>
            </span>
            <span v-if="loading" class="agent-editor-loading">加载中…</span>
          </div>
          <div
            class="agent-textarea-wrap"
            :class="{ 'is-loading': loading, 'is-readonly': overviewOnly }"
          >
            <textarea
              v-if="!overviewOnly"
              v-model="mdContent"
              class="agent-textarea"
              spellcheck="false"
              :disabled="loading"
              placeholder="Prompt 内容将在此显示…"
            />
            <div v-else class="agent-overview-placeholder">
              <p>「VLM 图片理解（总览）」不参与运行时 Prompt 渲染。</p>
              <p>请从上方芯片选择 <strong>图片类型分类</strong> 或各 <strong>描述</strong> 子 Agent 进行编辑。</p>
            </div>
          </div>
        </div>

        <footer class="agent-editor-footer">
          <button
            type="button"
            class="agent-save-btn"
            :disabled="loading || !canEditPrompt"
            @click="saveMd"
          >
            {{ loading ? '处理中…' : '保存 Prompt' }}
          </button>
          <span v-if="canEditPrompt" class="agent-save-path">
            backend/data/agents/{{ selectedMeta.agent_key }}/AGENT.md
          </span>
          <span v-else class="agent-save-path agent-save-path--muted">总览项不可保存</span>
        </footer>
      </template>

      <div v-else class="agent-empty">
        <p class="agent-empty-title">请选择一个 Agent</p>
        <p class="agent-empty-desc">在上方分类 Tab 中切换，再点选具体 Agent</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.agent-config-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 20px 24px 24px;
  background: #f8fafc;
  box-sizing: border-box;
}

.agent-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
  flex-shrink: 0;
}

.agent-page-title {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 800;
  color: #1e293b;
}

.agent-page-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}

.agent-page-desc code {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #475569;
  font-family: ui-monospace, monospace;
}

.agent-gateway-link {
  display: block;
  margin-top: 8px;
  color: #2563eb;
  font-weight: 700;
  text-decoration: none;
}

.agent-gateway-link:hover {
  text-decoration: underline;
}

.agent-page-toast {
  flex-shrink: 0;
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
}

.agent-page-toast.is-success {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.agent-page-toast.is-error {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.agent-global-alert {
  flex-shrink: 0;
  margin-bottom: 12px;
  padding: 10px 14px;
  font-size: 12px;
  line-height: 1.55;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
}

.agent-global-alert code {
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 4px;
  background: #fef3c7;
  font-family: ui-monospace, monospace;
}

/* ── 顶部：分类 Tab + 横向 Agent 卡片 ── */
.agent-picker {
  flex-shrink: 0;
  margin-bottom: 14px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.agent-group-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.agent-group-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #f8fafc;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.agent-group-tab:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.agent-group-tab.active {
  background: #363e42;
  border-color: #363e42;
  color: #fff;
}

.agent-group-tab-count {
  font-size: 10px;
  font-weight: 800;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.2);
  color: inherit;
}

.agent-group-tab:not(.active) .agent-group-tab-count {
  background: #e2e8f0;
  color: #64748b;
}

.agent-group-desc {
  margin: 0 0 10px;
  font-size: 11px;
  color: #94a3b8;
  line-height: 1.45;
}

.agent-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.agent-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}

.agent-chip--overview {
  border-style: dashed;
  background: #f8fafc;
}

.agent-chip--sub {
  padding-left: 12px;
}

.agent-chip:hover {
  border-color: #cbd5e1;
  background: #fafafa;
}

.agent-chip.active {
  border-color: #363e42;
  background: #fafafa;
  box-shadow: 0 0 0 1px #363e42;
}

.agent-chip-label {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  white-space: nowrap;
}

.agent-chip.active .agent-chip-label {
  color: #1e293b;
}

.agent-chip-tags {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.agent-tag {
  font-size: 9px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: 999px;
}

.agent-tag--lg {
  font-size: 10px;
  padding: 3px 10px;
}

.agent-tag--vlm {
  background: #f3e8ff;
  color: #7c3aed;
}

.agent-tag--llm {
  background: #dbeafe;
  color: #1d4ed8;
}

.agent-tag--dirty {
  background: #fef3c7;
  color: #92400e;
}

.agent-tag--info {
  background: #e0f2fe;
  color: #0369a1;
}

.agent-tag--sub {
  background: #f1f5f9;
  color: #64748b;
}

/* ── 运维说明 ── */
.agent-guide {
  margin-bottom: 12px;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  background: #f8fafc;
  overflow: hidden;
}

.agent-guide-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 10px 14px;
  border: none;
  background: #eef2ff;
  cursor: pointer;
  text-align: left;
}

.agent-guide-toggle-title {
  font-size: 12px;
  font-weight: 800;
  color: #3730a3;
}

.agent-guide-toggle-icon {
  font-size: 11px;
  font-weight: 700;
  color: #6366f1;
}

.agent-guide-body {
  padding: 12px 14px 14px;
  font-size: 12px;
  line-height: 1.55;
  color: #475569;
}

.agent-guide-warning {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
  font-weight: 600;
}

.agent-guide-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}

.agent-guide-block {
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #e2e8f0;
}

.agent-guide-block--full {
  margin-bottom: 10px;
}

.agent-guide-block p {
  margin: 0;
}

.agent-guide-h {
  margin: 0 0 6px;
  font-size: 11px;
  font-weight: 800;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.agent-guide-h--risk {
  color: #b91c1c;
}

.agent-guide-h--ok {
  color: #047857;
}

.agent-guide-h--no {
  color: #b45309;
}

.agent-guide-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 10px;
}

@media (max-width: 720px) {
  .agent-guide-columns {
    grid-template-columns: 1fr;
  }
}

.agent-guide-list {
  margin: 0;
  padding-left: 18px;
}

.agent-guide-list li {
  margin-bottom: 4px;
}

.agent-var-docs {
  margin: 0;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
}

.agent-var-docs dt {
  margin: 0;
}

.agent-var-docs dt code {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
}

.agent-var-docs dd {
  margin: 0;
}

.agent-guide-rollback {
  background: #ecfdf5;
  border-color: #a7f3d0;
}

.agent-guide-related {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.agent-guide-related-k {
  font-size: 10px;
  font-weight: 800;
  color: #94a3b8;
}

.agent-guide-related-v {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #475569;
  font-family: ui-monospace, monospace;
}

/* ── 编辑区全宽 ── */
.agent-editor {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}

.agent-editor-header {
  padding: 16px 18px 12px;
  border-bottom: 1px solid #e2e8f0;
  overflow-y: auto;
  max-height: 55vh;
}

.agent-editor-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
}

.agent-editor-title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: #1e293b;
}

.agent-editor-hint {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.55;
  color: #64748b;
}

.agent-meta-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 12px 20px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.agent-meta-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.agent-meta-item--vars {
  flex: 1;
  flex-wrap: wrap;
}

.agent-meta-k {
  font-size: 10px;
  font-weight: 800;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.agent-meta-v {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  padding: 3px 8px;
  border-radius: 6px;
  background: #fff;
  border: 1px solid #e2e8f0;
  color: #334155;
}

.agent-var-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.agent-var-chip {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  padding: 3px 8px;
  border-radius: 6px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
}

.agent-editor-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0 16px 16px;
}

.agent-editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 4px 8px;
}

.agent-editor-file {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}

.agent-editor-loading {
  font-size: 11px;
  color: #363e42;
  font-weight: 600;
}

.agent-textarea-wrap {
  flex: 1;
  min-height: 200px;
  border-radius: 12px;
  border: 1px solid #334155;
  background: #0f172a;
  overflow: hidden;
}

.agent-textarea-wrap.is-loading {
  opacity: 0.72;
}

.agent-textarea-wrap.is-readonly {
  border-style: dashed;
  border-color: #94a3b8;
  background: #f1f5f9;
}

.agent-textarea {
  width: 100%;
  height: 100%;
  min-height: 220px;
  box-sizing: border-box;
  padding: 16px 18px;
  border: none;
  outline: none;
  resize: none;
  font-family: ui-monospace, 'Cascadia Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.65;
  color: #e2e8f0;
  background: transparent;
}

.agent-textarea:disabled {
  cursor: wait;
}

.agent-overview-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 180px;
  padding: 24px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.agent-overview-placeholder p {
  margin: 0 0 8px;
}

.agent-editor-footer {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 18px;
  border-top: 1px solid #e2e8f0;
  background: #fafafa;
}

.agent-save-btn {
  font-size: 12px;
  font-weight: 800;
  color: #fff;
  background: #363e42;
  border: none;
  border-radius: 10px;
  padding: 9px 20px;
  cursor: pointer;
}

.agent-save-btn:hover:not(:disabled) {
  background: #4a5256;
}

.agent-save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.agent-save-path {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  color: #94a3b8;
}

.agent-save-path--muted {
  color: #cbd5e1;
}

.agent-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}

.agent-empty-title {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 800;
  color: #64748b;
}

.agent-empty-desc {
  margin: 0;
  font-size: 12px;
  color: #94a3b8;
}
</style>
