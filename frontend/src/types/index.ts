export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  intent?: string
  citations?: Array<{ document_name: string; snippet: string }>
  messageId?: number | null
  image?: string
}

export interface KnowledgeDoc {
  id: number
  filename: string
  status: string
  chunk_count: number
}
