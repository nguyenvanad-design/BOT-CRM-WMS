/**
 * Tokinarc frontend — src/components/ChatWidget.tsx
 * Thanh chat AI DÁN ĐÁY khung nội dung (giống mockup): tiêu đề + gợi ý nhanh +
 * ô nhập + nút Hỏi. Khi có hội thoại, tin nhắn hiện trong vùng cuộn phía trên
 * ô nhập (thu gọn được). Gọi chatbot service thật (POST /chatbot/api/v2/query).
 */
import { useEffect, useRef, useState } from 'react'
import { MessageCircle, Send, Loader2, ChevronDown, ChevronUp, Trash2 } from 'lucide-react'
import { askAssistant } from '@/lib/assistant'
import { apiError } from '@/lib/api'

interface Msg { role: 'user' | 'bot' | 'error'; text: string }

const SUGGESTIONS = [
  'Doanh thu hôm nay?',
  'Dong Nai Steel còn nợ bao nhiêu?',
  'Khách nào chưa mua 3 tháng?',
]

export function ChatWidget() {
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs, busy])

  const send = async (q: string) => {
    const query = q.trim()
    if (!query || busy) return
    setInput('')
    setExpanded(true)
    setMsgs((m) => [...m, { role: 'user', text: query }])
    setBusy(true)
    try {
      const r = await askAssistant(query)
      setMsgs((m) => [...m, { role: 'bot', text: r.text }])
    } catch (e) {
      setMsgs((m) => [...m, { role: 'error', text: apiError(e) }])
    } finally {
      setBusy(false)
    }
  }

  const clear = () => { setMsgs([]) }
  const hasMsgs = msgs.length > 0

  return (
    <div className="border-t border-line bg-ink-2 shrink-0">
      {/* Vùng hội thoại (khi có tin nhắn & đang mở) */}
      {hasMsgs && expanded && (
        <div ref={scrollRef} className="max-h-[40vh] overflow-y-auto px-4 py-3 space-y-2.5 border-b border-line">
          {msgs.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap break-words ${
                m.role === 'user' ? 'bg-flame text-white'
                : m.role === 'error' ? 'bg-danger/10 text-danger border border-danger/30'
                : 'bg-ink-3 text-txt'
              }`}>
                {m.text}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex justify-start">
              <div className="bg-ink-3 rounded-lg px-3 py-2 text-txt-2 text-sm flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" /> Đang trả lời…
              </div>
            </div>
          )}
        </div>
      )}

      {/* Thanh nhập */}
      <div className="px-4 py-3">
        <div className="flex items-center gap-2 mb-2">
          <MessageCircle size={15} className="text-flame" />
          <span className="text-sm font-semibold flex-1">Trợ lý CRM</span>
          {hasMsgs && (
            <>
              <button onClick={() => setExpanded((v) => !v)}
                className="text-txt-2 hover:text-txt p-1 flex items-center gap-1 text-[11px]">
                {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                {expanded ? 'Thu gọn' : 'Mở'}
              </button>
              <button onClick={clear} className="text-txt-2 hover:text-danger p-1" aria-label="Xóa hội thoại">
                <Trash2 size={14} />
              </button>
            </>
          )}
        </div>

        {/* Gợi ý nhanh (khi chưa có hội thoại) */}
        {!hasMsgs && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)}
                className="text-[11px] border border-line rounded-full px-2.5 py-1 text-txt-2
                           hover:border-flame hover:text-txt transition-colors">
                {s}
              </button>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') send(input) }}
            placeholder="Nhập câu hỏi…"
            className="flex-1 bg-ink-3 border border-line rounded-md px-3 py-2 text-sm
                       focus:border-flame focus:outline-none transition-colors"
          />
          <button
            onClick={() => send(input)}
            disabled={busy || !input.trim()}
            className="bg-flame hover:bg-flame-hi disabled:opacity-40 disabled:cursor-not-allowed
                       text-white rounded-md px-4 flex items-center gap-1.5 text-sm font-medium transition-colors"
          >
            <Send size={15} /> <span className="hidden sm:inline">Hỏi</span>
          </button>
        </div>
      </div>
    </div>
  )
}
