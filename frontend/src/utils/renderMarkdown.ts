import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ breaks: true, gfm: true })

export function renderMarkdown(raw: string): string {
  const text = String(raw || '')
  if (!text) return ''
  try {
    let html = marked.parse(text, { breaks: true, gfm: true }) as string
    html = DOMPurify.sanitize(html)
    return html
  } catch {
    return escapeHtml(text).replace(/\n/g, '<br>')
  }
}

export function renderStreamingText(raw: string): string {
  let t = escapeHtml(String(raw || ''))
  t = t.replace(/\n/g, '<br>')
  return t
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
