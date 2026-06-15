import type { ChatMessageItem, ChatSessionDetail, ChatSessionItem } from '../types'
import { intentDisplay } from './intentLabels'

function safeFileName(name: string): string {
  return name.replace(/[\\/:*?"<>|]/g, '_').replace(/\s+/g, '_').slice(0, 80) || 'session'
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

export function exportStamp(): string {
  const d = new Date()
  return `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}_${pad2(d.getHours())}${pad2(d.getMinutes())}`
}

function downloadText(filename: string, content: string, mimeType: string): void {
  const blob = new Blob(['\uFEFF', content], { type: `${mimeType};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function csvCell(v: unknown): string {
  const s = v == null ? '' : String(v)
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

const roleLabel = (role: string): string => {
  if (role === 'user') return '用户'
  if (role === 'assistant') return '助手'
  if (role === 'system') return '系统'
  return role
}

export function exportSessionJson(detail: ChatSessionDetail, messages: ChatMessageItem[]): void {
  const payload = {
    exported_at: new Date().toISOString(),
    session: {
      id: detail.id,
      context_id: detail.context_id,
      title: detail.title,
      status: detail.status,
      user_id: detail.user_id,
      created_at: detail.created_at,
      updated_at: detail.updated_at,
      message_count: detail.message_count,
      meta: detail.meta ?? null,
    },
    messages: messages.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      intent_label: m.intent_label ?? null,
      citations: m.citations ?? null,
      created_at: m.created_at,
    })),
  }
  const title = safeFileName(detail.title || `session_${detail.id}`)
  downloadText(`session-${detail.id}-${title}.json`, JSON.stringify(payload, null, 2), 'application/json')
}

export function exportSessionMarkdown(detail: ChatSessionDetail, messages: ChatMessageItem[]): void {
  const lines: string[] = []
  lines.push(`# ${detail.title || `会话 #${detail.id}`}`)
  lines.push('')
  lines.push(`- 会话 ID：${detail.id}`)
  lines.push(`- 追踪 ID：${detail.context_id}`)
  if (detail.user_id != null) lines.push(`- 用户 ID：${detail.user_id}`)
  lines.push(`- 创建时间：${detail.created_at ?? '—'}`)
  lines.push(`- 最后更新：${detail.updated_at ?? '—'}`)
  lines.push(`- 消息数：${messages.length}`)
  if (detail.meta?.last_intent) {
    lines.push(`- 最近意图：${intentDisplay(detail.meta.last_intent)}`)
  }
  if (detail.meta?.note) lines.push(`- 备注：${detail.meta.note}`)
  lines.push('')
  lines.push('---')
  lines.push('')

  for (const m of messages) {
    lines.push(`## ${roleLabel(m.role)} · #${m.id} · ${m.created_at ?? ''}`)
    if (m.intent_label) lines.push(`> 意图：${intentDisplay(undefined, m.intent_label)}`)
    lines.push('')
    lines.push(m.content)
    if (m.citations?.length) {
      lines.push('')
      lines.push('<details><summary>引用来源</summary>')
      lines.push('')
      lines.push('```json')
      lines.push(JSON.stringify(m.citations, null, 2))
      lines.push('```')
      lines.push('')
      lines.push('</details>')
    }
    lines.push('')
    lines.push('---')
    lines.push('')
  }

  const title = safeFileName(detail.title || `session_${detail.id}`)
  downloadText(`session-${detail.id}-${title}.md`, lines.join('\n'), 'text/markdown')
}

export function exportSessionListCsv(sessions: ChatSessionItem[]): void {
  const header = ['ID', '追踪ID', '名称', '创建时间', '最后更新', '消息数', '最近意图', '备注']
  const rows = sessions.map((s) => [
    s.id,
    s.context_id,
    s.title || '',
    s.created_at ?? '',
    s.updated_at ?? '',
    s.message_count ?? s.meta?.message_count ?? 0,
    s.meta?.last_intent ? intentDisplay(s.meta.last_intent) : '',
    s.meta?.note ?? '',
  ])
  const csv = [header, ...rows].map((row) => row.map(csvCell).join(',')).join('\n')
  downloadText(`sessions-export-${exportStamp()}.csv`, csv, 'text/csv')
}
