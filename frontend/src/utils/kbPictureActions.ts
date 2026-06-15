/** 知识库图片：放大查看、复制到剪贴板 */

export async function copyKbImage(src: string): Promise<boolean> {
  const url = String(src || '').trim()
  if (!url) return false
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error('fetch failed')
    const blob = await res.blob()
    if (navigator.clipboard?.write && typeof ClipboardItem !== 'undefined') {
      const type = blob.type || 'image/png'
      await navigator.clipboard.write([new ClipboardItem({ [type]: blob })])
      return true
    }
  } catch {
    /* 降级复制链接 */
  }
  try {
    await navigator.clipboard.writeText(new URL(url, window.location.origin).href)
    return true
  } catch {
    return false
  }
}

export function handleKbPictureClick(
  e: MouseEvent,
  onZoom: (src: string) => void,
): boolean {
  const el = e.target as HTMLElement
  const zoomBtn = el.closest('[data-kb-zoom]')
  const copyBtn = el.closest('[data-kb-copy]')
  const img = el.closest('.kb-picture-zoomable') as HTMLImageElement | null

  const resolveSrc = (): string => {
    const fig = el.closest('.kb-picture-block') as HTMLElement | null
    return (
      fig?.dataset.kbSrc ||
      img?.dataset.kbSrc ||
      img?.src ||
      ''
    )
  }

  if (zoomBtn || (img && !copyBtn)) {
    const src = resolveSrc()
    if (src) {
      e.preventDefault()
      e.stopPropagation()
      onZoom(src)
      return true
    }
  }

  if (copyBtn) {
    e.preventDefault()
    e.stopPropagation()
    const src = resolveSrc()
    if (src) void copyKbImage(src)
    return true
  }

  return false
}
