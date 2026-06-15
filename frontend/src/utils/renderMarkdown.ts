import DOMPurify from 'dompurify'
import { marked } from 'marked'
import type { RagCitationSlice } from '../types'
import {
  PICTURE_BLOCK_DETECT_RE,
  PICTURE_BLOCK_RE,
  renderPictureBlocks,
} from './pictureBlocks'

marked.setOptions({ breaks: true, gfm: true })

export type RenderMarkdownOptions = {
  /** 用于引用锚点 #cite-slice-{messageScope}-{refId} */
  messageScope?: string | number
  messageId?: number | null
  /** @deprecated 不再自动从切片注入图片，由 AI 在正文中按需插入 picture 块 */
  citationSlices?: RagCitationSlice[]
}

function sanitizeRichHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ['sup', 'figure', 'figcaption', 'img', 'div', 'span', 'br', 'button'],
    ADD_ATTR: ['href', 'title', 'class', 'src', 'alt', 'loading', 'data-rag-ref', 'data-kb-src', 'data-kb-zoom', 'data-kb-copy', 'type'],
  })
}

export function citeSliceDomId(messageScope: string | number, refId: number): string {
  return `cite-slice-${messageScope}-${refId}`
}

/** 与 ChatAssistantMessage 兼容：messageId 为空时用 draft */
export function sliceAnchorId(messageId: number | null | undefined, refId: number): string {
  const scope = messageId != null ? String(messageId) : 'draft'
  return citeSliceDomId(scope, refId)
}

function resolveScope(opts?: RenderMarkdownOptions): string {
  if (opts?.messageScope != null && opts.messageScope !== '') return String(opts.messageScope)
  if (opts?.messageId != null) return String(opts.messageId)
  return '0'
}

function buildCiteSup(n: string, scope: string): string {
  const anchor = `#${citeSliceDomId(scope, Number(n))}`
  return `<sup class="rag-cite-sup"><a href="${anchor}" class="rag-cite-link" title="跳转到文献切片 [${n}]">[${n}]</a></sup>`
}

/** 将 ,3,4 / ，3，4 / 、3、4 等连续引用号转为多个上标 */
function expandCommaCiteSeq(seq: string, scope: string): string {
  const nums = [...seq.matchAll(/(\d{1,2})/g)].map((m) => m[1])
  return nums.map((n) => buildCiteSup(n, scope)).join('')
}

/** 将正文中的引用号转为上标可点击 [N] 链接 */
export function linkifyCitations(text: string, messageScope?: string | number): string {
  if (!text) return text
  const scope = messageScope != null && messageScope !== '' ? String(messageScope) : '0'
  const citeSup = (n: string) => buildCiteSup(n, scope)

  let out = text
  // 标准 [N] 格式
  out = out.replace(/\[(\d{1,2})\]/g, (_m, n: string) => citeSup(n))

  // [N] 或上标后的逗号/顿号引用列表：,3,4 、3、4
  out = out.replace(/(?:[,、，]\s*\d{1,2})+/g, (match, offset, full) => {
    const prev = full.slice(Math.max(0, offset - 24), offset)
    if (/(?:<\/sup>|\]|[\u4e00-\u9fff）)」』"\u201d])$/.test(prev)) {
      return expandCommaCiteSeq(match, scope)
    }
    return match
  })

  // 中文或括号后直接跟引用号：模块2,3,4。
  out = out.replace(
    /([\u4e00-\u9fff）)」』"\u201d])(\d{1,2}(?:[,、，]\s*\d{1,2})*)(?=[。，,.；;!！?？\n\r)\]）]|$)/gm,
    (_m, before: string, seq: string) => `${before}${expandCommaCiteSeq(seq, scope)}`,
  )

  // 中文/字母与单个引用号之间有空格：功能 2。
  out = out.replace(
    /([\u4e00-\u9fffA-Za-z0-9）)」』"\u201d])\s+(\d{1,2})(?=[。，,.；;!！?？\n\r)\]）]|\s*$)/gm,
    (_m, before: string, n: string) => `${before}${citeSup(n)}`,
  )
  return out
}

function preprocess(raw: string, opts?: RenderMarkdownOptions): string {
  const scope = resolveScope(opts)
  let text = String(raw || '')
  text = renderPictureBlocks(text)
  text = linkifyCitations(text, scope)
  return text
}

export function renderMarkdown(raw: string, opts?: RenderMarkdownOptions): string {
  const text = preprocess(raw, opts)
  if (!text) return ''
  try {
    let html = marked.parse(text, { breaks: true, gfm: true }) as string
    html = sanitizeRichHtml(html)
    return html
  } catch {
    return escapeHtml(text).replace(/\n/g, '<br>')
  }
}

export function renderStreamingText(raw: string, opts?: RenderMarkdownOptions): string {
  const mixed = preprocess(String(raw || ''), opts)
  if (!mixed) return ''
  return escapePlainPreservingHtml(mixed)
}

/** 切片全文：picture 块渲染 + 引用上标 + 纯文本换行 */
export function renderSliceContent(raw: string, messageScope?: string | number): string {
  const scope = messageScope != null && messageScope !== '' ? String(messageScope) : '0'
  const text = String(raw || '')
  if (!text) return ''
  const linkPlain = (chunk: string): string => {
    const linked = linkifyCitations(chunk, scope)
    return escapePlainPreservingHtml(linked)
  }
  if (!PICTURE_BLOCK_DETECT_RE.test(text)) {
    return linkPlain(text)
  }
  const parts: string[] = []
  const re = new RegExp(PICTURE_BLOCK_RE.source, 'gi')
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    const plain = text.slice(last, m.index)
    if (plain.trim()) {
      parts.push(`<div class="rag-slice-text">${linkPlain(plain)}</div>`)
    }
    parts.push(renderPictureBlocks(m[0]))
    last = m.index + m[0].length
  }
  const tail = text.slice(last)
  if (tail.trim()) {
    parts.push(`<div class="rag-slice-text">${linkPlain(tail)}</div>`)
  }
  return sanitizeRichHtml(parts.join(''))
}

/** 注释正文：引用上标 + 换行保留 */
export function renderAnnotationContent(raw: string, messageScope?: string | number): string {
  const linked = linkifyCitations(String(raw || ''), messageScope)
  if (!linked) return ''
  return sanitizeRichHtml(escapePlainPreservingHtml(linked))
}

function escapePlainPreservingHtml(text: string): string {
  const htmlBlockRe = /(<figure[\s\S]*?<\/figure>|<sup[\s\S]*?<\/sup>)/g
  const parts: string[] = []
  let last = 0
  let m: RegExpExecArray | null
  while ((m = htmlBlockRe.exec(text))) {
    if (m.index > last) {
      parts.push(escapeHtml(text.slice(last, m.index)).replace(/\n/g, '<br>'))
    }
    parts.push(m[1])
    last = m.index + m[0].length
  }
  if (last < text.length) {
    parts.push(escapeHtml(text.slice(last)).replace(/\n/g, '<br>'))
  }
  return sanitizeRichHtml(parts.join(''))
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
