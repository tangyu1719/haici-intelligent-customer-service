import { onUnmounted, ref, type Ref } from 'vue'

/** Web Speech API 类型补充（Chrome / Edge） */
interface SpeechRecognitionEventLike extends Event {
  resultIndex: number
  results: SpeechRecognitionResultList
}

interface SpeechRecognitionErrorEventLike extends Event {
  error: string
  message?: string
}

interface SpeechRecognitionLike extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onstart: ((ev: Event) => void) | null
  onend: ((ev: Event) => void) | null
  onerror: ((ev: SpeechRecognitionErrorEventLike) => void) | null
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
}

export interface UseSpeechInputOptions {
  lang?: string
  onText: (text: string) => void
}

export interface UseSpeechInputReturn {
  supported: Ref<boolean>
  listening: Ref<boolean>
  error: Ref<string>
  start: (anchorText?: string) => void
  stop: () => void
  toggle: (anchorText?: string) => void
}

const ERROR_LABELS: Record<string, string> = {
  'not-allowed': '麦克风权限被拒绝，请在浏览器设置中允许访问',
  'service-not-allowed': '当前环境不允许使用语音识别',
  'no-speech': '未检测到语音，请重试',
  'audio-capture': '未找到可用麦克风',
  'network': '语音识别需要网络连接',
  'aborted': '',
}

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null
  return window.SpeechRecognition || window.webkitSpeechRecognition || null
}

export function isSpeechInputSupported(): boolean {
  return !!getRecognitionCtor()
}

export function useSpeechInput(options: UseSpeechInputOptions): UseSpeechInputReturn {
  const supported = ref(isSpeechInputSupported())
  const listening = ref(false)
  const error = ref('')

  let recognition: SpeechRecognitionLike | null = null
  let anchorText = ''
  let committedText = ''
  let manualStop = false

  const mapError = (code: string): string => {
    if (code === 'aborted') return ''
    return ERROR_LABELS[code] || `语音识别失败（${code}）`
  }

  const applyText = (interim: string): void => {
    const merged = `${anchorText}${committedText}${interim}`
    options.onText(merged)
  }

  const disposeRecognition = (): void => {
    if (!recognition) return
    recognition.onstart = null
    recognition.onend = null
    recognition.onerror = null
    recognition.onresult = null
    recognition = null
  }

  const stop = (): void => {
    manualStop = true
    listening.value = false
    if (recognition) {
      try {
        recognition.stop()
      } catch {
        /* ignore */
      }
    }
    disposeRecognition()
  }

  const start = (anchor = ''): void => {
    if (!supported.value || listening.value) return
    const Ctor = getRecognitionCtor()
    if (!Ctor) {
      supported.value = false
      error.value = '当前浏览器不支持语音输入，请使用 Chrome 或 Edge'
      return
    }

    manualStop = false
    anchorText = anchor
    committedText = ''
    error.value = ''

    recognition = new Ctor()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = options.lang || 'zh-CN'
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      listening.value = true
    }

    recognition.onresult = (ev: SpeechRecognitionEventLike) => {
      let interim = ''
      for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
        const piece = ev.results[i][0]?.transcript || ''
        if (ev.results[i].isFinal) {
          committedText += piece
        } else {
          interim += piece
        }
      }
      applyText(interim)
    }

    recognition.onerror = (ev: SpeechRecognitionErrorEventLike) => {
      const msg = mapError(ev.error)
      if (msg) error.value = msg
      if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed' || ev.error === 'audio-capture') {
        manualStop = true
        listening.value = false
      }
    }

    recognition.onend = () => {
      if (manualStop) {
        listening.value = false
        disposeRecognition()
        return
      }
      // 浏览器自动结束（如静音超时）时尝试续听
      if (listening.value && recognition) {
        try {
          recognition.start()
        } catch {
          listening.value = false
          disposeRecognition()
        }
      }
    }

    try {
      recognition.start()
    } catch {
      error.value = '无法启动语音识别，请稍后重试'
      listening.value = false
      disposeRecognition()
    }
  }

  const toggle = (anchor = ''): void => {
    if (listening.value) stop()
    else start(anchor)
  }

  onUnmounted(stop)

  return { supported, listening, error, start, stop, toggle }
}
