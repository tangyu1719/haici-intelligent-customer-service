/** 意图英文码 → 中文描述（与后端 term_dictionary.INTENT_LABELS 对齐） */
export const INTENT_LABELS: Record<string, string> = {
  product_consult: '产品介绍',
  after_sale: '售后问题',
  chitchat: '闲聊',
  complaint: '投诉反馈',
  faq_cached: 'FAQ 缓存',
}

export function intentDisplay(code?: string, label?: string): string {
  const c = (code || '').trim()
  const zh = (label || INTENT_LABELS[c] || c || '未知').trim()
  if (!c) return zh
  if (zh === c) return c
  return `${zh}（${c}）`
}
