<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { authHeaders } from '../api/auth'
import type { ChatMessage, FeedbackSubmitPayload, IntentAlternativesResponse } from '../types'
import { INTENT_LABELS, intentDisplay } from '../utils/intentLabels'
import { handleKbPictureClick } from '../utils/kbPictureActions'
import {
  answerBodyForMsg,
  hydrateMsgCitations,
  ragCitationAnnotationsForMsg,
  ragCitationSlicesForMsg,
} from '../utils/ragCitations'
import { renderMarkdown, renderSliceContent, renderStreamingText, renderAnnotationContent, citeSliceDomId } from '../utils/renderMarkdown'

const props = defineProps<{
  msg: ChatMessage
  userQuestion?: string
  sessionId?: number | null
  contextId?: string
  contextSummary?: string
}>()

const emit = defineEmits<{
  followUp: [text: string]
}>()

const slicesOpen = ref(false)
const annoOpen = ref(false)
const sliceDetailOpen = ref<Record<number, boolean>>({})
const lightboxSrc = ref('')

const sliceHtmlCache = new Map<string, string>()

watch(
  () => props.msg.messageId,
  () => {
    sliceHtmlCache.clear()
    sliceDetailOpen.value = {}
  },
)

const slices = computed(() => ragCitationSlicesForMsg(props.msg))

const annotations = computed(() => ragCitationAnnotationsForMsg(props.msg))

const messageScope = computed(() => String(props.msg.messageId ?? props.contextId ?? 'draft'))

// 流式结束后一次性解析引用，避免 computed 内重复 hydrate
watch(
  () => [props.msg.messageId, props.msg.isStreaming] as const,
  () => {
    if (!props.msg.isStreaming) hydrateMsgCitations(props.msg)
  },
  { immediate: true },
)

const bodyHtml = computed(() => {
  const raw = answerBodyForMsg(props.msg)
  if (!raw && !props.msg.isStreaming) return ''
  const opts = {
    messageId: props.msg.messageId ?? null,
    messageScope: messageScope.value,
    citationSlices: slices.value,
  }
  if (props.msg.isStreaming) return renderStreamingText(raw, opts)
  return renderMarkdown(raw, opts)
})

const getAnnotationHtml = (text: string): string => {
  const key = `${messageScope.value}:anno:${text.slice(0, 48)}`
  const cached = sliceHtmlCache.get(key)
  if (cached) return cached
  const html = renderAnnotationContent(text, messageScope.value)
  sliceHtmlCache.set(key, html)
  return html
}

const getSliceHtml = (refId: number, content: string): string => {
  const key = `${messageScope.value}:${refId}`
  const cached = sliceHtmlCache.get(key)
  if (cached) return cached
  const html = renderSliceContent(content, messageScope.value)
  sliceHtmlCache.set(key, html)
  return html
}

const citeSliceId = (refId: number): string => citeSliceDomId(messageScope.value, refId)

const isSliceDetailOpen = (refId: number): boolean => sliceDetailOpen.value[refId] === true

const toggleSliceDetail = (refId: number, open?: boolean): void => {
  sliceDetailOpen.value[refId] = open ?? !isSliceDetailOpen(refId)
}

const onCitationClick = (e: MouseEvent): void => {
  if (handleKbPictureClick(e, (src) => { lightboxSrc.value = src })) return
  const a = (e.target as HTMLElement).closest('a.rag-cite-link') as HTMLAnchorElement | null
  if (!a?.hash) return
  e.preventDefault()
  const id = a.hash.slice(1)
  const el = document.getElementById(id)
  if (!el) return
  slicesOpen.value = true
  const refMatch = id.match(/-(\d+)$/)
  if (refMatch) sliceDetailOpen.value[Number(refMatch[1])] = true
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  el.classList.add('rag-cite-item--highlight')
  window.setTimeout(() => el.classList.remove('rag-cite-item--highlight'), 1800)
}

const onSliceContentClick = (e: MouseEvent): void => {
  if (handleKbPictureClick(e, (src) => { lightboxSrc.value = src })) return
  onCitationClick(e)
}

const closeLightbox = (): void => {
  lightboxSrc.value = ''
}
const intentLiked = ref<boolean | null>(null)
const starRating = ref(0)
const hoverStar = ref(0)
const commentText = ref('')
const ratingSubmitting = ref(false)
const commentSubmitting = ref(false)
const intentSubmitting = ref(false)
const ratingSubmitted = ref(false)
const commentSubmitted = ref(false)
const intentSubmitted = ref(false)
const ratingError = ref('')
const commentError = ref('')
const intentError = ref('')

const intentAlt = ref<IntentAlternativesResponse | null>(null)
const altLoading = ref(false)
const altError = ref('')
const selectedCode = ref('')
const selectedLabel = ref('')
const customIntentText = ref('')
const suggestionsShown = ref<string[]>([])

const intentText = computed(() => intentDisplay(props.msg.intent, props.msg.intentLabel))

const answerTime = computed((): string => {
  const s = props.msg.createdAt
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}/${dd} ${hh}:${mi}`
})

const showMsgMeta = computed(
  () => !!(props.msg.intent || props.msg.intentLabel) || (!props.msg.isStreaming && !!answerTime.value),
)

const fallbackBuiltin = computed(() =>
  Object.entries(INTENT_LABELS)
    .filter(([code]) => code !== (props.msg.intent || ''))
    .map(([code, label]) => ({ code, label, source: 'builtin' })),
)

const builtinOptions = computed(() => intentAlt.value?.builtin?.length ? intentAlt.value.builtin : fallbackBuiltin.value)

const suggestedOptions = computed(() => intentAlt.value?.suggested || [])

const termHints = computed(() => {
  const fromApi = intentAlt.value?.term_hints || []
  const fromPipeline = props.msg.pipeline?.retrieval_terms || []
  const seen = new Set<string>()
  const out: string[] = []
  for (const t of [...fromApi, ...fromPipeline]) {
    const s = String(t).trim()
    if (s && !seen.has(s)) {
      seen.add(s)
      out.push(s)
    }
  }
  return out.slice(0, 8)
})

const correctionReady = computed(() => {
  if (intentLiked.value !== false) return true
  return !!(selectedLabel.value.trim() || customIntentText.value.trim())
})

const showCommentBox = computed(() => starRating.value > 0 && starRating.value < 5)

const buildContextSnapshot = (includeCorrection = false): FeedbackSubmitPayload['contextSnapshot'] => {
  const detectedCode = props.msg.intent || ''
  const detectedLabel = props.msg.intentLabel || intentText.value
  let correctedLabel = selectedLabel.value.trim()
  if (intentLiked.value === false && customIntentText.value.trim() && !correctedLabel) {
    correctedLabel = customIntentText.value.trim()
  }
  return {
    session_id: props.sessionId || 0,
    context_id: props.contextId || '',
    context_summary: props.contextSummary || '',
    user_question: props.userQuestion || '',
    assistant_answer: answerBodyForMsg(props.msg) || props.msg.content,
    intent: detectedCode,
    intent_label: detectedLabel,
    detected_intent: detectedCode,
    detected_intent_label: detectedLabel,
    corrected_intent: includeCorrection && intentLiked.value === false ? selectedCode.value || undefined : undefined,
    corrected_intent_label: includeCorrection && intentLiked.value === false ? correctedLabel : undefined,
    intent_suggestions_shown: includeCorrection && intentLiked.value === false ? suggestionsShown.value : undefined,
  }
}

const parseFeedbackError = async (res: Response): Promise<string> => {
  try {
    const err = await res.json()
    const detail = err?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const msgs = detail.map((x: { msg?: string }) => x.msg || '').filter(Boolean)
      if (msgs.length) return msgs.join('；')
    }
  } catch {
    /* ignore */
  }
  return `反馈提交失败（HTTP ${res.status}）`
}

const postFeedback = async (body: Record<string, unknown>): Promise<true | string> => {
  if (!props.msg.messageId) return '消息无效'
  try {
    const res = await fetch(`/api/v1/feedback/messages/${props.msg.messageId}`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(body),
    })
    if (!res.ok) return await parseFeedbackError(res)
    return true
  } catch {
    return '网络异常，反馈提交失败'
  }
}

const attachIntentToBody = (body: Record<string, unknown>): void => {
  if (intentLiked.value === true) body.intent_liked = true
  else if (intentLiked.value === false && correctionReady.value) body.intent_liked = false
}

const canSubmitIntentNow = (): boolean => ratingSubmitted.value || starRating.value > 0

const submitIntentFeedback = async (includeCorrection = false): Promise<void> => {
  if (!props.msg.messageId || intentLiked.value === null || intentSubmitting.value) return
  if (!canSubmitIntentNow()) return
  if (intentLiked.value === false && includeCorrection && !correctionReady.value) {
    intentError.value = '请选择或填写您认为的正确意图'
    return
  }
  intentSubmitting.value = true
  intentError.value = ''
  const body: Record<string, unknown> = {
    intent_liked: intentLiked.value,
    context_snapshot: buildContextSnapshot(includeCorrection),
  }
  const result = await postFeedback(body)
  intentSubmitting.value = false
  if (result === true) {
    intentSubmitted.value = true
    intentError.value = ''
    return
  }
  intentError.value = typeof result === 'string' ? result : '意图评价提交失败'
}

const submitRating = async (n: number): Promise<void> => {
  if (!props.msg.messageId || ratingSubmitting.value) return
  starRating.value = n
  ratingSubmitting.value = true
  ratingError.value = ''
  const body: Record<string, unknown> = {
    rating: n,
    context_snapshot: buildContextSnapshot(intentLiked.value === false && correctionReady.value),
  }
  attachIntentToBody(body)
  const result = await postFeedback(body)
  ratingSubmitting.value = false
  if (result === true) {
    ratingSubmitted.value = true
    ratingError.value = ''
    intentError.value = ''
    if (n === 5) commentText.value = ''
    return
  }
  ratingError.value = typeof result === 'string' ? result : '评分提交失败'
}

const submitCommentOnly = async (): Promise<void> => {
  if (!props.msg.messageId || !showCommentBox.value || commentSubmitting.value) return
  const text = commentText.value.trim()
  if (!text) {
    commentError.value = '请填写补充说明，或无需提交'
    return
  }
  commentSubmitting.value = true
  commentError.value = ''
  const body: Record<string, unknown> = {
    comment: text,
    context_snapshot: buildContextSnapshot(intentLiked.value === false && correctionReady.value),
  }
  if (!ratingSubmitted.value && starRating.value > 0) body.rating = starRating.value
  attachIntentToBody(body)
  const result = await postFeedback(body)
  commentSubmitting.value = false
  if (result === true) {
    commentSubmitted.value = true
    ratingSubmitted.value = true
    commentError.value = ''
    return
  }
  commentError.value = typeof result === 'string' ? result : '补充说明提交失败'
}

const toggleSlices = (): void => {
  slicesOpen.value = !slicesOpen.value
}

const toggleAnno = (): void => {
  annoOpen.value = !annoOpen.value
}

const clearCorrection = (): void => {
  intentAlt.value = null
  altError.value = ''
  selectedCode.value = ''
  selectedLabel.value = ''
  customIntentText.value = ''
  suggestionsShown.value = []
}

const loadIntentAlternatives = async (): Promise<void> => {
  if (!props.msg.messageId) return
  altLoading.value = true
  altError.value = ''
  try {
    const terms = (props.msg.pipeline?.retrieval_terms || []).join(',')
    const qs = new URLSearchParams({ message_id: String(props.msg.messageId) })
    if (terms) qs.set('retrieval_terms', terms)
    const res = await fetch(`/api/v1/chat/intent-alternatives?${qs}`, { headers: authHeaders() })
    if (res.ok) {
      intentAlt.value = await res.json()
      suggestionsShown.value = intentAlt.value?.intent_suggestions_shown || []
    } else {
      altError.value = '备选意图加载失败，请从下方选择或自行填写'
    }
  } catch {
    altError.value = '备选意图加载失败，请从下方选择或自行填写'
  } finally {
    altLoading.value = false
  }
}

const setIntentLike = async (liked: boolean): Promise<void> => {
  intentLiked.value = liked
  intentError.value = ''
  if (!liked) {
    await loadIntentAlternatives()
    return
  }
  clearCorrection()
  await submitIntentFeedback(false)
}

const pickBuiltin = (code: string, label: string): void => {
  selectedCode.value = code
  selectedLabel.value = label
  customIntentText.value = ''
  void submitIntentFeedback(true)
}

const pickSuggested = (code: string, label: string): void => {
  selectedCode.value = code && code !== 'unknown' ? code : ''
  selectedLabel.value = label
  customIntentText.value = ''
  void submitIntentFeedback(true)
}

const pickTermHint = (term: string): void => {
  selectedCode.value = ''
  selectedLabel.value = term
  customIntentText.value = ''
  void submitIntentFeedback(true)
}

const applyCustomIntent = (): void => {
  const t = customIntentText.value.trim()
  if (!t) return
  selectedCode.value = ''
  selectedLabel.value = t
  void submitIntentFeedback(true)
}
</script>

<template>
  <div class="assistant-msg-wrap">
    <Teleport to="body">
      <div v-if="lightboxSrc" class="kb-lightbox" @click="closeLightbox">
        <div class="kb-lightbox-inner" @click.stop>
          <button type="button" class="kb-lightbox-close" title="关闭" @click="closeLightbox">✕</button>
          <img class="kb-lightbox-img" :src="lightboxSrc" alt="" />
        </div>
      </div>
    </Teleport>

    <div class="msg-answer-card msg-bubble msg-bubble--assistant">
      <div v-if="showMsgMeta" class="msg-meta-row">
        <span v-if="msg.intent || msg.intentLabel" class="msg-meta-intent">意图识别：{{ intentText }}</span>
        <span v-if="answerTime && !msg.isStreaming" class="msg-meta-time">回答时间 {{ answerTime }}</span>
      </div>

      <div
        v-if="msg.content || msg.isStreaming"
        class="chat-prose"
        :class="{ 'is-streaming': msg.isStreaming }"
        v-html="bodyHtml"
        @click="onCitationClick"
      />

      <div v-if="!msg.isStreaming && slices.length" class="msg-rag-cite-wrap">
        <div class="rag-cite-panel-flat">
          <div class="rag-cite-bar rag-cite-bar--panel rag-cite-bar--flat">
            <span class="rag-cite-bar-title">文献切片明细 · {{ slices.length }} 条</span>
            <button type="button" class="rag-cite-bar-action rag-cite-bar-action--text" @click="toggleSlices">
              {{ slicesOpen ? '收起 ▲' : '展开 ▼' }}
            </button>
          </div>
          <ol v-if="slicesOpen" class="web-search-list rag-cite-list">
            <li
              v-for="sl in slices"
              :key="'cite-s-' + sl.ref_id + '-' + (sl.source_file || sl.parent_name)"
              :id="citeSliceId(sl.ref_id)"
              class="web-search-item rag-cite-item"
            >
              <div
                class="rag-cite-bar rag-cite-bar--item"
                :class="{ 'rag-cite-bar--item-only': !isSliceDetailOpen(sl.ref_id) }"
              >
                <span class="rag-cite-bar-title">
                  <span class="rag-ref-tag">[{{ sl.ref_id }}]</span>
                  <span class="rag-cite-bar-name">{{ sl.parent_name }}</span>
                </span>
                <button
                  type="button"
                  class="rag-cite-bar-action"
                  @click="toggleSliceDetail(sl.ref_id)"
                >
                  {{ isSliceDetailOpen(sl.ref_id) ? '收起 ▲' : '展开 ▼' }}
                </button>
              </div>
              <div v-if="sl.source_file" class="rag-cite-meta web-search-url">父文档路径：{{ sl.source_file }}</div>
              <div v-if="isSliceDetailOpen(sl.ref_id)" class="rag-cite-expanded">
                <div
                  class="rag-cite-body rag-cite-body--rich"
                  v-html="getSliceHtml(sl.ref_id, sl.slice_content)"
                  @click="onSliceContentClick"
                />
              </div>
              <span v-if="sl.score != null" class="rag-cite-score">score {{ Number(sl.score).toFixed(4) }}</span>
            </li>
          </ol>
        </div>
      </div>

      <div v-if="!msg.isStreaming && annotations.length" class="msg-rag-cite-wrap">
        <div class="rag-cite-panel-flat">
          <div class="rag-cite-bar rag-cite-bar--panel rag-cite-bar--flat">
            <span class="rag-cite-bar-title">注释 · {{ annotations.length }} 条</span>
            <button type="button" class="rag-cite-bar-action rag-cite-bar-action--text" @click="toggleAnno">
              {{ annoOpen ? '收起 ▲' : '展开 ▼' }}
            </button>
          </div>
          <ol v-if="annoOpen" class="web-search-list rag-cite-list rag-anno-list">
            <li
              v-for="an in annotations"
              :key="'cite-a-' + an.index"
              class="web-search-item rag-cite-item rag-anno-item"
            >
              <div class="rag-anno-head">注释 {{ an.index }}</div>
              <div
                class="rag-cite-body rag-anno-body chat-prose"
                v-html="getAnnotationHtml(an.text)"
                @click="onCitationClick"
              />
            </li>
          </ol>
        </div>
      </div>

      <div v-if="!msg.isStreaming && msg.followUps?.length" class="follow-up-block">
        <p class="follow-up-title">你可能还想问</p>
        <div class="follow-up-chips">
          <button
            v-for="(q, idx) in msg.followUps"
            :key="'fu-' + idx + '-' + q.slice(0, 12)"
            type="button"
            class="follow-up-chip"
            @click="emit('followUp', q)"
          >
            {{ q }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="!msg.isStreaming && msg.messageId" class="msg-feedback-card">
      <div v-if="msg.intent || msg.intentLabel" class="intent-feedback-row">
        <div class="intent-feedback-head">
          <span v-if="msg.intent || msg.intentLabel" class="intent-label">意图识别：{{ intentText }}</span>
          <span class="intent-like-hint">如果觉得 AI 理解准确的话，请别吝啬你的赞！</span>
          <div class="intent-like-btns">
            <button
              type="button"
              class="intent-like-btn"
              :class="{ active: intentLiked === true, success: intentSubmitted && intentLiked === true }"
              :disabled="intentSubmitting || (intentSubmitted && intentLiked === true)"
              @click="setIntentLike(true)"
            >
              {{ intentSubmitting && intentLiked === true ? '提交中…' : intentSubmitted && intentLiked === true ? '已评价' : '👍 理解准确' }}
            </button>
            <button
              type="button"
              class="intent-like-btn dislike"
              :class="{ active: intentLiked === false }"
              :disabled="intentSubmitting"
              @click="setIntentLike(false)"
            >
              👎 理解有误
            </button>
          </div>
        </div>
        <p v-if="intentError" class="submit-error intent-inline-error">{{ intentError }}</p>

        <div v-if="intentLiked === false" class="intent-correction-panel">
          <p class="correction-title">推测您可能想问的是</p>
          <p v-if="altLoading" class="correction-hint">正在加载备选意图与 AI 推测…</p>
          <p v-else-if="altError" class="correction-warn">{{ altError }}</p>

          <div v-if="builtinOptions.length" class="correction-group">
            <span class="correction-tag">标准意图</span>
            <div class="correction-options">
              <button
                v-for="opt in builtinOptions"
                :key="'b-' + opt.code"
                type="button"
                class="correction-opt"
                :class="{ on: selectedCode === opt.code && selectedLabel === opt.label }"
                @click="pickBuiltin(opt.code, opt.label)"
              >
                {{ opt.label }}
              </button>
            </div>
          </div>

          <div v-if="suggestedOptions.length" class="correction-group">
            <span class="correction-tag">AI 推测</span>
            <div class="correction-options">
              <button
                v-for="(sug, i) in suggestedOptions"
                :key="'s-' + i + sug.label"
                type="button"
                class="correction-opt correction-opt-llm"
                :class="{ on: selectedLabel === sug.label }"
                @click="pickSuggested(sug.code, sug.label)"
              >
                {{ sug.label }}
                <span v-if="sug.summary" class="correction-opt-sub">{{ sug.summary }}</span>
              </button>
            </div>
          </div>

          <div v-if="termHints.length" class="correction-group">
            <span class="correction-tag">相关主题</span>
            <div class="correction-options">
              <button
                v-for="term in termHints"
                :key="'t-' + term"
                type="button"
                class="correction-opt correction-opt-term"
                :class="{ on: selectedLabel === term && !selectedCode }"
                @click="pickTermHint(term)"
              >
                {{ term }}
              </button>
            </div>
          </div>

          <div class="correction-custom">
            <label class="correction-custom-label">其他意图（自填）</label>
            <input
              v-model="customIntentText"
              type="text"
              class="correction-custom-input"
              maxlength="64"
              placeholder="您认为正确的意图是…"
              @blur="applyCustomIntent"
            />
          </div>

          <p v-if="selectedLabel" class="correction-selected">已选：{{ selectedLabel }}</p>
        </div>
      </div>

      <div class="satisfaction-block">
        <p class="satisfaction-title">此次回答是否满意？</p>
        <div class="star-row">
          <button
            v-for="n in 5"
            :key="n"
            type="button"
            class="star-btn"
            :class="{ on: n <= (hoverStar || starRating) }"
            :disabled="ratingSubmitting"
            @mouseenter="hoverStar = n"
            @mouseleave="hoverStar = 0"
            @click="submitRating(n)"
          >
            ★
          </button>
          <span v-if="starRating" class="star-label">
            {{ ratingSubmitting ? '提交中…' : ratingSubmitted ? `已评 ${starRating} 星` : `${starRating} 星` }}
          </span>
        </div>
        <p v-if="ratingError" class="submit-error">{{ ratingError }}</p>
        <template v-if="showCommentBox">
          <textarea
            v-model="commentText"
            class="feedback-comment"
            rows="2"
            maxlength="500"
            placeholder="补充说明（选填）：哪里满意或不满意？"
          />
          <p v-if="commentError" class="submit-error">{{ commentError }}</p>
          <button
            type="button"
            class="feedback-submit"
            :class="{ success: commentSubmitted }"
            :disabled="commentSubmitting || commentSubmitted || !commentText.trim()"
            @click="submitCommentOnly"
          >
            {{ commentSubmitting ? '提交中…' : commentSubmitted ? '提交成功' : '提交补充说明' }}
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.assistant-msg-wrap {
  width: 100%;
}
.msg-answer-card {
  width: 100%;
}
.msg-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(54, 62, 66, 0.1);
}
.msg-meta-intent {
  font-size: 11px;
  font-weight: 700;
  color: #d97706;
}
.msg-meta-time {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  margin-left: auto;
}
.msg-feedback-card {
  margin-top: 12px;
  width: 50%;
  max-width: 100%;
  min-width: 280px;
  padding: 12px 14px;
  border-radius: 16px;
  background: #ffffff;
  border: 1px solid rgba(54, 62, 66, 0.2);
  box-shadow:
    0 2px 10px rgba(15, 23, 42, 0.07),
    0 0 0 1px rgba(148, 163, 184, 0.22);
}
@media (max-width: 768px) {
  .msg-feedback-card {
    width: 100%;
  }
}
.follow-up-block {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.06), rgba(217, 119, 6, 0.05));
  border: 1px solid rgba(37, 99, 235, 0.12);
}
.follow-up-title {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 800;
  color: #2563eb;
}
.follow-up-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.follow-up-chip {
  font-size: 11px;
  font-weight: 600;
  color: #1e40af;
  background: #fff;
  border: 1px solid rgba(37, 99, 235, 0.25);
  border-radius: 999px;
  padding: 6px 14px;
  cursor: pointer;
  line-height: 1.35;
  max-width: 100%;
  text-align: left;
}
.follow-up-chip:hover {
  background: rgba(37, 99, 235, 0.08);
}
.intent-feedback-row {
  margin-bottom: 12px;
}
.intent-feedback-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: nowrap;
  width: 100%;
  min-width: 0;
}
.intent-label {
  font-size: 11px;
  font-weight: 700;
  color: #d97706;
  flex-shrink: 0;
  white-space: nowrap;
}
.intent-like-hint {
  font-size: 10px;
  color: #64748b;
  margin: 0;
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.intent-like-btns {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  margin-left: auto;
}
.intent-inline-error {
  margin-top: 6px;
}
.intent-like-btn {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  background: #fff;
  cursor: pointer;
}
.intent-like-btn.active {
  border-color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
  color: #15803d;
}
.intent-like-btn.dislike.active {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.08);
  color: #b91c1c;
}
.intent-like-btn.success {
  border-color: #22c55e;
  background: rgba(34, 197, 94, 0.12);
  color: #15803d;
}
.intent-correction-panel {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #fef2f2;
  border: 1px solid rgba(239, 68, 68, 0.2);
}
.correction-title {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 800;
  color: #b91c1c;
}
.correction-hint,
.correction-warn {
  font-size: 10px;
  margin: 0 0 8px;
  color: #64748b;
}
.correction-warn {
  color: #dc2626;
}
.correction-group {
  margin-bottom: 10px;
}
.correction-tag {
  display: block;
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
  margin-bottom: 6px;
}
.correction-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.correction-opt {
  font-size: 11px;
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  background: #fff;
  cursor: pointer;
  text-align: left;
}
.correction-opt.on {
  border-color: #dc2626;
  background: rgba(239, 68, 68, 0.1);
  color: #b91c1c;
  font-weight: 700;
}
.correction-opt-llm {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}
.correction-opt-sub {
  font-size: 9px;
  color: #64748b;
  font-weight: 400;
}
.correction-custom {
  margin-top: 8px;
}
.correction-custom-label {
  display: block;
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
  margin-bottom: 4px;
}
.correction-custom-input {
  width: 100%;
  box-sizing: border-box;
  font-size: 11px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  border-radius: 8px;
  padding: 6px 8px;
}
.correction-selected {
  margin: 8px 0 0;
  font-size: 10px;
  font-weight: 700;
  color: #15803d;
}
.satisfaction-block {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(54, 62, 66, 0.08);
}
.satisfaction-title {
  font-size: 11px;
  font-weight: 700;
  color: #363e42;
  margin: 0 0 8px;
}
.star-row {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 8px;
}
.star-btn {
  font-size: 20px;
  line-height: 1;
  color: #cbd5e1;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 2px;
}
.star-btn.on {
  color: #f59e0b;
}
.star-label {
  font-size: 11px;
  color: #64748b;
  margin-left: 6px;
}
.feedback-comment {
  width: 100%;
  box-sizing: border-box;
  font-size: 11px;
  border: 1px solid rgba(54, 62, 66, 0.15);
  border-radius: 8px;
  padding: 8px;
  resize: vertical;
  margin-bottom: 8px;
}
.submit-error {
  font-size: 10px;
  color: #dc2626;
  margin: 0 0 6px;
}
.feedback-submit {
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  background: #363e42;
  border: none;
  border-radius: 8px;
  padding: 6px 14px;
  cursor: pointer;
}
.feedback-submit:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.feedback-submit.success {
  background: #15803d;
  opacity: 1;
  cursor: default;
}
</style>
