/** 解析 RAG picture 块并转为可渲染 HTML（对齐后端 build_rag_image_block） */

export const PICTURE_BLOCK_DETECT_RE = /\{picture_id\s*:/

/** description 可选：回答里 AI 可只输出 picture_id + url */
export const PICTURE_BLOCK_RE =
  /\{picture_id\s*:\s*([^;}\n]+?)\s*;\s*url\s*:\s*([^;}\n]+?)\s*(?:;\s*description\s*:\s*([\s\S]*?))?\s*\}/gi

/** 绝对路径 / output 相对路径 → 前端可访问的 /output/... URL */
export function absPathToPublicUrl(rawPath: string): string {
  let p = String(rawPath || '').trim()
  // 处理JSON转义的双反斜杠
  p = p.replace(/\\\\/g, '\\')
  // Windows路径 → URL
  p = p.replace(/\\/g, '/')
  if (!p) return ''
  if (p.startsWith('/output/')) return p
  const outIdx = p.toLowerCase().indexOf('/output/')
  if (outIdx >= 0) return p.slice(outIdx)
  const kbIdx = p.toLowerCase().indexOf('kb_assets/')
  if (kbIdx >= 0) return `/output/${p.slice(kbIdx).replace(/^\/+/, '')}`
  const outOnly = p.toLowerCase().indexOf('output/')
  if (outOnly >= 0) return `/${p.slice(outOnly).replace(/^\/+/, '')}`
  // 兜底：直接返回（可能是相对路径）
  if (p.startsWith('/')) return p
  return ''
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** 用户可见：仅图片 + 放大/复制，不展示 picture_id 与 description */
export function renderPictureFigure(imgUrl: string): string {
  if (!imgUrl) return ''
  const src = escapeHtml(imgUrl)
  return (
    `<figure class="kb-picture-block" data-kb-src="${src}">` +
    `<div class="kb-picture-toolbar">` +
    `<button type="button" class="kb-picture-btn" data-kb-zoom title="放大查看">🔍 放大</button>` +
    `<button type="button" class="kb-picture-btn" data-kb-copy title="复制图片">📋 复制</button>` +
    `</div>` +
    `<img class="kb-picture-img kb-picture-zoomable" src="${src}" alt="" loading="lazy" data-kb-src="${src}" />` +
    `</figure>`
  )
}

/** 将文本中的 {picture_id:...} 块替换为仅图片 HTML（description 仅供 AI，不渲染） */
export function renderPictureBlocks(text: string): string {
  if (!text || !PICTURE_BLOCK_DETECT_RE.test(text)) return text
  return text.replace(PICTURE_BLOCK_RE, (_full, _pictureId: string, url: string) => {
    const imgUrl = absPathToPublicUrl(url)
    return renderPictureFigure(imgUrl)
  })
}

/** @deprecated 不再自动内联切片全部图片，由 AI 在正文中按需插入 picture 块 */
export function renderPicturesFromSlice(sliceContent: string): string {
  if (!sliceContent || !PICTURE_BLOCK_DETECT_RE.test(sliceContent)) return ''
  const re = new RegExp(PICTURE_BLOCK_RE.source, 'gi')
  const blocks: string[] = []
  let m: RegExpExecArray | null
  while ((m = re.exec(sliceContent))) {
    const html = renderPictureBlocks(m[0])
    if (html && html !== m[0]) blocks.push(html)
  }
  return blocks.join('\n\n')
}
