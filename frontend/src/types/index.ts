export interface RagCitationSlice {
  ref_id: number
  parent_name: string
  source_file?: string
  slice_content: string
  score?: number
}

export interface RagCitationAnnotation {
  index: number
  text: string
}

export interface ChatAttachment {
  type: 'image' | 'file'
  name: string
  path: string
  preview?: string
}

export interface ChatPendingUpload {
  type: 'image' | 'file'
  name: string
  preview?: string
  file?: File
  path?: string
  uploading?: boolean
  error?: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  intent?: string
  intentLabel?: string
  citations?: Array<Record<string, unknown>>
  ragPrefetchSlices?: Array<Record<string, unknown>>
  ragCitationSlices?: RagCitationSlice[]
  ragCitationAnnotations?: RagCitationAnnotation[]
  answerBody?: string
  isStreaming?: boolean
  messageId?: number | null
  image?: string
  attachments?: ChatAttachment[]
  llmProvider?: string
  llmNodeName?: string
  llmModel?: string
  /** SSE follow_ups：回答结束后的追问建议 */
  followUps?: string[]
  /** SSE meta.pipeline */
  pipeline?: {
    source?: string
    rewritten_query?: string
    query_keywords?: string[]
    retrieval_terms?: string[]
    rag_query?: string
  }
  /** 助手消息落库/完成时间（ISO） */
  createdAt?: string
}

export interface FeedbackContextSnapshot {
  session_id: number
  context_id: string
  context_summary: string
  user_question: string
  assistant_answer: string
  intent?: string
  intent_label?: string
  detected_intent?: string
  detected_intent_label?: string
  corrected_intent?: string
  corrected_intent_label?: string
  intent_suggestions_shown?: string[]
}

export interface IntentAlternativeBuiltin {
  code: string
  label: string
  source: string
}

export interface IntentAlternativeSuggested {
  code: string
  label: string
  summary?: string
  source: string
}

export interface IntentAlternativesResponse {
  ok: boolean
  detected_intent: string
  detected_intent_label: string
  builtin: IntentAlternativeBuiltin[]
  suggested: IntentAlternativeSuggested[]
  term_hints: string[]
  intent_suggestions_shown: string[]
  llm_powered: boolean
}

export interface FeedbackSubmitPayload {
  messageId: number
  rating: number
  intentLiked: boolean | null
  comment: string
  contextSnapshot: FeedbackContextSnapshot
}

export interface FeedbackAdminItem {
  id: number
  message_id: number
  user_id: number
  username?: string | null
  nickname?: string | null
  rating: number
  intent_liked?: boolean | null
  comment?: string | null
  context_snapshot?: FeedbackContextSnapshot | null
  created_at: string
  session_id?: number | null
  context_id?: string
  user_question?: string
  assistant_answer?: string
  context_summary?: string
  intent?: string
  intent_label?: string
  corrected_intent?: string
  corrected_intent_label?: string
  session_title?: string
}

export interface LlmGatewayNode {
  id: string
  name: string
  provider: string
  base_url: string
  model: string
  priority: number
  status: string
  tags: string[]
  api_key_hint: string
}

export interface LlmGatewaySnapshot {
  route_mode: string
  task_type_route: Record<string, string>
  active_chat: {
    node_id: string
    name: string
    provider: string
    model: string
    base_url: string
  }
  nodes: LlmGatewayNode[]
}

export interface PlatformHealthItem {
  id: string
  label: string
  status: 'ok' | 'warn' | 'error'
  latency_ms?: number
  error?: string
  detail?: Record<string, unknown>
  settings_href?: string
}

export interface PlatformHealthSnapshot {
  ready: boolean
  all_ok: boolean
  summary: { ok: number; warn: number; error: number }
  items: PlatformHealthItem[]
  error?: string
}

export interface SessionMetaSummary {
  last_intent?: string | null
  message_count?: number
  note?: string | null
  pinned?: boolean
}

export interface ChatSessionItem {
  id: number
  context_id: string
  title: string
  created_at?: string
  updated_at?: string
  message_count?: number
  meta?: SessionMetaSummary | null
}

export interface ChatMessageItem {
  id: number
  role: string
  content: string
  intent_label?: string | null
  citations?: Record<string, unknown>[] | null
  created_at: string
}

export interface ChatSessionDetail extends ChatSessionItem {
  status?: number
  user_id?: number
  message_count: number
  messages?: ChatMessageItem[]
}

export interface KnowledgeDoc {
  id: number
  filename: string
  status: string
  chunk_count: number
  file_type?: string
  file_size_bytes?: number
  file_size_human?: string
  image_count?: number
  vlm_limit?: number
  truncated?: boolean
  error_message?: string | null
  kb_id?: number | null
  kb_name?: string | null
}

export interface KnowledgeBase {
  id: number
  name: string
  description?: string | null
  is_default: number
  status: number
  doc_count: number
  created_at: string
  updated_at?: string | null
}

export interface KnowledgeBaseBrief {
  id: number
  name: string
  is_default: number
  doc_count: number
}
