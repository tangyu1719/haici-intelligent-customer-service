/** 修复后端/历史任务中 GBK→Latin 误读导致的中文文件名乱码 */
export function fixDisplayFilename(name: string | null | undefined): string {
  const raw = (name || '').trim()
  if (!raw || /[\u4e00-\u9fff]/.test(raw)) return raw
  if (!/[À-ÿÃÔËÎÖúÊÓÃ»§²á]/.test(raw)) return raw
  try {
    const bytes = new Uint8Array([...raw].map((ch) => ch.charCodeAt(0) & 0xff))
    const dec = new TextDecoder('gbk').decode(bytes)
    if (dec && /[\u4e00-\u9fff]/.test(dec)) return dec
  } catch {
    /* ignore */
  }
  return raw
}
