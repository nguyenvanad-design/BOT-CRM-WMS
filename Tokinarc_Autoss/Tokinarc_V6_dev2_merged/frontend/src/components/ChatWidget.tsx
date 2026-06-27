/**
 * Tokinarc frontend — src/components/ChatWidget.tsx
 * Thanh chat TRỢ LÝ NỘI BỘ dán đáy (KHÁC bot khách). Gọi Django assistant thật
 * (POST /analytics/assistant/query/, JWT+role). Tùy role, làm được: báo giá,
 * soạn hợp đồng, phiếu nhập/xuất kho, báo cáo CEO, đánh giá kế hoạch, tra cứu.
 */
import { useEffect, useRef, useState } from 'react'
import { MessageCircle, Send, Loader2, ChevronDown, ChevronUp, Trash2, Paperclip, X } from 'lucide-react'
import { askAssistant } from '@/lib/assistant'
import { apiError } from '@/lib/api'
import { useAuth } from '@/lib/auth/store'
import type { Role } from '@/lib/types'

interface Msg { role: 'user' | 'bot' | 'error'; text: string }

/** Gợi ý RIÊNG theo vai trò — chỉ gợi việc role đó ĐƯỢC PHÉP làm với AI. */
function suggestionsFor(role?: Role): string[] {
  switch (role) {
    case 'sales':        // NV kinh doanh — bán hàng của mình
      return [
        'Tạo lead Nguyễn Văn A, công ty ABC, 0901234567',
        'Làm báo giá cho Công ty ABC: 5 x 001002',
        'Soạn hợp đồng từ báo giá BG-0007',
        'Tra cứu phụ tùng 001002',
      ]
    case 'manager':      // Quản lý kinh doanh — điều hành sales + tài chính
      return [
        'Doanh thu tháng này?',
        'Đánh giá kế hoạch pipeline',
        'Khách nào chưa mua 3 tháng?',
        'Top khách hàng',
      ]
    case 'ceo':          // CEO — toàn cảnh điều hành
      return [
        'Báo cáo điều hành',
        'Doanh thu tháng này?',
        'Công nợ khách hàng',
        'Top khách hàng',
      ]
    case 'warehouse':    // NV kho — thao tác kho + kỹ thuật
      return [
        'Nhập kho 100 x 001002',
        'Xuất kho 20 x 001002',
        'Tồn của 001002 ở các kho',
        'Cách thay liner TK-308RR',
      ]
    case 'wh_manager':   // Quản lý kho — tồn + vận hành kho
      return [
        'Tồn của 001002 ở các kho',
        'Nhập kho 100 x 001002',
        'Bộ tiêu hao cho súng TK-308RR',
        'Tra cứu lắp đặt / sửa chữa',
      ]
    case 'service':      // Kỹ sư dịch vụ — kỹ thuật/lắp đặt/sửa chữa
      return [
        'Cách thay liner TK-308RR',
        'Quy trình lắp đặt súng hàn',
        'Bộ tiêu hao cho TK-308RR',
        'Tra cứu phụ tùng 001002',
      ]
    case 'admin':
      return [
        'Báo cáo điều hành',
        'Doanh thu tháng này?',
        'Tra cứu phụ tùng 001002',
      ]
    default:             // mặc định — chỉ tra cứu
      return ['Tra cứu phụ tùng 001002', 'Tra cứu súng hàn']
  }
}

export function ChatWidget() {
  const role = useAuth((s) => s.user?.role)
  const SUGGESTIONS = suggestionsFor(role)
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(true)
  const [file, setFile] = useState<File | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs, busy])

  const send = async (q: string) => {
    const query = q.trim()
    if ((!query && !file) || busy) return
    const sentFile = file
    setInput(''); setFile(null)
    setExpanded(true)
    setMsgs((m) => [...m, {
      role: 'user',
      text: (query || '(phân tích file đính kèm)') + (sentFile ? `\n📎 ${sentFile.name}` : ''),
    }])
    setBusy(true)
    try {
      const r = await askAssistant(query || 'Phân tích file này giúp tôi', sentFile)
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
          <span className="text-sm font-semibold flex-1">Trợ lý nội bộ</span>
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

        {/* Chip file đính kèm */}
        {file && (
          <div className="flex items-center gap-2 mb-2 text-xs bg-ink-3 border border-line rounded-md px-2.5 py-1.5 w-fit max-w-full">
            <Paperclip size={13} className="text-flame shrink-0" />
            <span className="truncate">{file.name}</span>
            <span className="text-txt-2 shrink-0">({Math.ceil(file.size / 1024)}KB)</span>
            <button onClick={() => setFile(null)} className="text-txt-2 hover:text-danger shrink-0"><X size={13} /></button>
          </div>
        )}

        <div className="flex gap-2">
          <input ref={fileRef} type="file" className="hidden"
            accept="image/*,.pdf,.xlsx,.xls,.csv,.txt"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) setFile(f); e.target.value = '' }} />
          <button onClick={() => fileRef.current?.click()} disabled={busy} title="Đính kèm ảnh/PDF/Excel"
            className="border border-line rounded-md px-2.5 text-txt-2 hover:text-flame hover:border-flame
                       disabled:opacity-40 transition-colors flex items-center">
            <Paperclip size={16} />
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') send(input) }}
            placeholder={file ? 'Hỏi gì về file này… (Enter để phân tích)' : 'Nhập câu hỏi…'}
            className="flex-1 bg-ink-3 border border-line rounded-md px-3 py-2 text-sm
                       focus:border-flame focus:outline-none transition-colors"
          />
          <button
            onClick={() => send(input)}
            disabled={busy || (!input.trim() && !file)}
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
