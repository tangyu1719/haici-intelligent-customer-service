import type { ChatMessage, RagCitationAnnotation, RagCitationSlice } from '../types'
import { fixDisplayFilename, fixMojibakeText } from './filename'

export function splitAnswerBodyAndCitations(text: string): {
  body: string
  sliceSection: string
  annoSection: string
} {
  const sliceIdx = text.search(/#{1,3}\s*文献切片明细/)
  const annoIdx = text.search(/#{1,3}\s*注释/)
  let body = text
  let sliceSection = ''
  let annoSection = ''
  if (sliceIdx >= 0) {
    const end = annoIdx > sliceIdx ? annoIdx : text.length
    sliceSection = text.slice(sliceIdx, end).replace(/^#{1,3}\s*文献切片明细\s*/m, '').trim()
    body = text.slice(0, sliceIdx).trim()
  }
  if (annoIdx >= 0) {
    annoSection = text.slice(annoIdx).replace(/^#{1,3}\s*注释\s*/m, '').trim()
    if (annoIdx < 0 || sliceIdx < 0 || annoIdx < sliceIdx) body = text.slice(0, annoIdx).trim()
  }
  body = body.replace(/\n?---\s*$/, '').trim()
  return { body, sliceSection, annoSection }
}

export function parseSlicesFromMarkdown(section: string): RagCitationSlice[] {
  if (!String(section || '').trim()) return []
  const re = /[-•]\s*切片\[(\d+)\][：:]([\s\S]*?)(?=\n[-•]\s*切片\[|\n#{1,3}\s|$)/g
  const out: RagCitationSlice[] = []
  let m: RegExpExecArray | null
  while ((m = re.exec(section))) {
    const block = String(m[2] || '').trim()
    const parentM = block.match(/所属父文档[《「]([^》」]+)[》」](?:[（(]([^）)]+)[）)])?/)
    const sliceM = block.match(/切片全文[：:]\s*([\s\S]*?)(?=\n\s*父文档全文|$)/)
    let parentPath = ''
    const pathM = block.match(/父文档全文[：:]\s*([\s\S]*?)(?=\n\s*[-•]|$)/)
    if (pathM) {
      const p = String(pathM[1] || '').trim()
      const seeM = p.match(/见路径\s*([^\s，,；;]+)/)
      if (seeM) parentPath = seeM[1].trim()
      else if (!/前端可点击|点击查看/.test(p)) parentPath = p
    }
    if (!parentPath && parentM?.[2]) parentPath = String(parentM[2]).trim()
    out.push({
      ref_id: Number(m[1]),
      parent_name: fixDisplayFilename(parentM ? String(parentM[1]).trim() : '知识库片段'),
      source_file: fixDisplayFilename(parentPath),
      slice_content: fixMojibakeText((sliceM ? sliceM[1] : block).trim()),
    })
  }
  return out
}

export function parseAnnotationsFromMarkdown(section: string): RagCitationAnnotation[] {
  if (!String(section || '').trim()) return []
  return String(section)
    .split(/\n/)
    .map((line) => {
      const t = line.trim()
      if (!t) return null
      const m = t.match(/^(\d+)(?:\.\s*|\s+)([\s\S]+)/)
      if (!m) return null
      return { index: Number(m[1]), text: String(m[2]).trim() }
    })
    .filter(Boolean) as RagCitationAnnotation[]
}

export function prefetchSliceToCitation(sl: Record<string, unknown>, fallbackIndex = 0): RagCitationSlice | null {
  if (!sl || typeof sl !== 'object') return null
  const parent = fixDisplayFilename(String(sl.parent_name || sl.parent_document || sl.title || '知识库片段'))
  let refId = Number(sl.ref_id)
  if (!Number.isFinite(refId) || refId < 1) refId = fallbackIndex + 1
  return {
    ref_id: refId,
    parent_name: parent,
    source_file: fixDisplayFilename(String(sl.source_file || '').trim()),
    slice_content: fixMojibakeText(String(sl.content || sl.slice_content || sl.snippet || '').trim()),
    score: typeof sl.score === 'number' ? sl.score : undefined,
  }
}

export function normalizeSliceRefIds(slices: RagCitationSlice[]): RagCitationSlice[] {
  return slices.map((sl, i) => ({
    ...sl,
    ref_id: sl.ref_id > 0 ? sl.ref_id : i + 1,
  }))
}

export function hydrateMsgCitations(msg: ChatMessage): void {
  if (!msg || msg.role !== 'assistant') return
  const raw = String(msg.content || '')
  const { body, sliceSection, annoSection } = splitAnswerBodyAndCitations(raw)
  msg.answerBody = body
  const parsed = parseSlicesFromMarkdown(sliceSection)
  if (msg.ragPrefetchSlices?.length) {
    msg.ragCitationSlices = msg.ragPrefetchSlices
      .map((s, i) => prefetchSliceToCitation(s as Record<string, unknown>, i))
      .filter(Boolean) as RagCitationSlice[]
  } else if (parsed.length) {
    msg.ragCitationSlices = parsed
  } else if (!msg.ragCitationSlices?.length) {
    msg.ragCitationSlices = []
  }
  msg.ragCitationSlices = normalizeSliceRefIds(msg.ragCitationSlices || [])
  msg.ragCitationAnnotations = parseAnnotationsFromMarkdown(annoSection)
}

export function answerBodyForMsg(msg: ChatMessage): string {
  if (!msg) return ''
  if (msg.isStreaming) {
    const raw = String(msg.content || '')
    const { body } = splitAnswerBodyAndCitations(raw)
    return body || raw
  }
  if (msg.answerBody != null) return String(msg.answerBody)
  hydrateMsgCitations(msg)
  return String(msg.answerBody != null ? msg.answerBody : msg.content || '')
}

export function ragCitationSlicesForMsg(msg: ChatMessage): RagCitationSlice[] {
  if (!msg) return []
  if (msg.ragCitationSlices?.length) return msg.ragCitationSlices
  if (msg.ragPrefetchSlices?.length) {
    return normalizeSliceRefIds(
      msg.ragPrefetchSlices
        .map((s, i) => prefetchSliceToCitation(s as Record<string, unknown>, i))
        .filter(Boolean) as RagCitationSlice[],
    )
  }
  hydrateMsgCitations(msg)
  return normalizeSliceRefIds(msg.ragCitationSlices || [])
}

export function ragCitationAnnotationsForMsg(msg: ChatMessage): RagCitationAnnotation[] {
  if (!msg) return []
  if (msg.ragCitationAnnotations?.length) return msg.ragCitationAnnotations
  hydrateMsgCitations(msg)
  return msg.ragCitationAnnotations || []
}
