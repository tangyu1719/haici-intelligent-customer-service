/** 修复后端/历史任务中 UTF-8/GBK→Latin 误读导致的中文乱码 */
export function fixDisplayFilename(name: string | null | undefined): string {
  const raw = (name || '').trim()
  if (!raw || /[\u4e00-\u9fff]/.test(raw)) return raw
  if (!/[\u0080-\u00ff]/.test(raw) && !/[À-ÿ]/.test(raw)) return raw

  const tryDecode = (encoding: string): string | null => {
    try {
      const bytes = new Uint8Array([...raw].map((ch) => ch.charCodeAt(0) & 0xff))
      const dec = new TextDecoder(encoding).decode(bytes)
      if (dec && /[\u4e00-\u9fff]/.test(dec) && !/[\u0080-\u00ff]{3,}/.test(dec)) return dec
    } catch {
      /* ignore */
    }
    return null
  }

  // UTF-8 被当成 Latin-1 读取（ÔËÍ¬… 类乱码）
  const utf8 = tryDecode('utf-8')
  if (utf8) return utf8

  // GBK 被当成 Latin-1 读取
  const gbk = tryDecode('gbk')
  if (gbk) return gbk

  return raw
}

/** 修复长文本中嵌入的文件名乱码片段 */
export function fixMojibakeText(text: string | null | undefined): string {
  const raw = String(text || '')
  if (!raw) return raw
  return raw.replace(/[^\s\n\r]{3,80}?\.(?:docx|pdf|xlsx|txt|md)/gi, (m) => fixDisplayFilename(m) || m)
}
