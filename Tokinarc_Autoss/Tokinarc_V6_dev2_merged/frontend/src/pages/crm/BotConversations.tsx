/**
 * Tokinarc frontend — src/pages/crm/BotConversations.tsx
 * INBOX ĐA KÊNH: Website · Zalo OA · Facebook · Instagram → một hộp thư.
 * Bot trả lời trước; nhân viên tiếp quản khi cần. Đọc/quản lý qua JWT + role.
 */
import { useState, type ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Inbox, Send, Flag, CheckCircle2, User, Bot, Globe, AlertCircle, Hand, Phone, StickyNote,
} from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { PageHeader, Card, Button } from '@/components/ui'
import { toast } from 'sonner'

interface Msg { id: number; role: 'user' | 'bot' | 'agent'; role_display: string; text: string; intent: string; created_at: string }
interface Conv {
  id: string; session_key: string; channel: string; channel_display: string
  customer_name: string; customer_phone: string; lead: string | null
  owner: number | null; owner_username: string | null
  status: string; status_display: string; flagged: boolean
  message_count: number; unread: number; last_message_at: string | null; last_preview: string; created_at: string
  messages?: Msg[]
}

// ── Nhận diện kênh: nhãn + màu thương hiệu + ký hiệu badge ───────────────────
const CH: Record<string, { label: string; cls: string; sym: ReactNode }> = {
  web:       { label: 'Website',   cls: 'bg-flame/15 text-flame',           sym: <Globe size={13} /> },
  zalo:      { label: 'Zalo OA',   cls: 'bg-blue-500/15 text-blue-400',     sym: <b className="text-[11px]">Z</b> },
  facebook:  { label: 'Facebook',  cls: 'bg-[#1877F2]/20 text-[#5c9bf5]',   sym: <b className="text-[11px]">f</b> },
  instagram: { label: 'Instagram', cls: 'bg-pink-500/15 text-pink-400',     sym: <b className="text-[10px]">IG</b> },
  whatsapp:  { label: 'WhatsApp',  cls: 'bg-emerald-500/15 text-emerald-400', sym: <b className="text-[10px]">Wa</b> },
}
const chMeta = (c: string) => CH[c] ?? { label: c || 'Website', cls: 'bg-ink-3 text-txt-2', sym: <Globe size={13} /> }

const CHANNEL_TABS = [
  { key: '', label: 'Tất cả' },
  { key: 'web', label: 'Website' },
  { key: 'zalo', label: 'Zalo OA' },
  { key: 'facebook', label: 'Facebook' },
  { key: 'instagram', label: 'Instagram' },
]

const QUICK_REPLIES = [
  'Dạ em gửi bảng giá chi tiết ạ 📄',
  'Anh/chị cho em xin SĐT để báo giá kỹ hơn nha',
  'Bên em còn hàng ạ, anh/chị cần số lượng bao nhiêu?',
  'Em kết nối kỹ thuật tư vấn thêm cho mình nhé?',
]

function statusChip(c: Conv): { label: string; cls: string; icon: ReactNode } {
  if (c.status === 'closed') return { label: 'Đã đóng', cls: 'bg-ink-3 text-txt-2 border-line', icon: <CheckCircle2 size={11} /> }
  if (c.owner_username) return { label: c.owner_username, cls: 'bg-ok/12 text-ok border-ok/30', icon: <User size={11} /> }
  if (c.status === 'needs_human') return { label: 'Cần người xử lý', cls: 'bg-danger/12 text-danger border-danger/30', icon: <AlertCircle size={11} /> }
  return { label: 'Bot đang trả lời', cls: 'bg-blue-500/12 text-blue-400 border-blue-500/30', icon: <Bot size={11} /> }
}

function clock(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const sameDay = new Date().toDateString() === d.toDateString()
  return sameDay ? d.toLocaleTimeString('vi', { hour: '2-digit', minute: '2-digit' })
                 : d.toLocaleDateString('vi', { day: '2-digit', month: '2-digit' })
}

export function BotConversationsPage() {
  const qc = useQueryClient()
  const [channel, setChannel] = useState('')
  const [closed, setClosed] = useState(false)
  const [hot, setHot] = useState(false)
  const [sel, setSel] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [mode, setMode] = useState<'reply' | 'note'>('reply')

  const list = useQuery({
    queryKey: ['bot-conversations', channel, closed, hot],
    queryFn: async () => (await api.get<{ count: number; results: Conv[] }>('/crm/bot-conversations/', {
      params: { channel: channel || undefined, status: closed ? 'closed' : undefined, flagged: hot ? 'true' : undefined },
    })).data,
    refetchInterval: 15000,
  })
  const rows = (list.data?.results ?? []).filter((c) => closed || c.status !== 'closed')

  const detail = useQuery({
    queryKey: ['bot-conversation', sel],
    queryFn: async () => (await api.get<Conv>(`/crm/bot-conversations/${sel}/`)).data,
    enabled: !!sel,
    refetchInterval: 10000,   // thread đang mở tự cập nhật tin khách mới đến (~10s)
  })
  const conv = detail.data

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['bot-conversations'] })
    qc.invalidateQueries({ queryKey: ['bot-conversation', sel] })
  }
  const post = (path: string, body?: unknown, ok?: string) => ({
    mutationFn: () => api.post(`/crm/bot-conversations/${sel}/${path}/`, body ?? {}),
    onSuccess: () => { if (ok) toast.success(ok); refresh() },
    onError: (e: unknown) => toast.error(apiError(e)),
  })
  const takeover = useMutation(post('takeover', undefined, 'Đã tiếp quản — bot ngừng tự trả lời'))
  const flag = useMutation(post('flag'))
  const close = useMutation(post('close', undefined, 'Đã đóng hội thoại'))
  const send = useMutation({
    mutationFn: () => api.post(`/crm/bot-conversations/${sel}/${mode}/`, { text: draft.trim() }),
    onSuccess: () => { setDraft(''); refresh() },
    onError: (e) => toast.error(apiError(e)),
  })
  const openConv = (id: string) => { setSel(id); setDraft(''); setMode('reply') }

  return (
    <div className="max-w-6xl">
      <PageHeader icon={<Inbox size={20} className="text-flame" />} title="Inbox đa kênh"
        subtitle="Website · Zalo OA · Facebook · Instagram → một hộp thư · bot trả lời trước, bàn giao người khi cần" />

      {/* Tab kênh + lọc nhanh */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        {CHANNEL_TABS.map((t) => (
          <button key={t.key} onClick={() => setChannel(t.key)}
            className={`px-3 py-1.5 rounded-full text-sm border transition ${channel === t.key
              ? 'bg-flame text-white border-flame' : 'border-line text-txt-2 hover:text-txt'}`}>
            {t.label}
          </button>
        ))}
        <span className="flex-1" />
        <button onClick={() => setHot((v) => !v)}
          className={`px-3 py-1.5 rounded-full text-sm border flex items-center gap-1.5 ${hot
            ? 'bg-warn/15 text-warn border-warn/40' : 'border-line text-txt-2 hover:text-txt'}`}>
          <Flag size={13} /> Khách nóng
        </button>
        <button onClick={() => setClosed((v) => !v)}
          className={`px-3 py-1.5 rounded-full text-sm border ${closed
            ? 'bg-ink-3 text-txt border-line' : 'border-line text-txt-2 hover:text-txt'}`}>
          {closed ? 'Đã đóng' : 'Đang mở'}
        </button>
      </div>

      <div className="grid md:grid-cols-[minmax(300px,380px)_1fr] gap-4">
        {/* DANH SÁCH */}
        <Card className="p-0 overflow-hidden">
          <div className="max-h-[72vh] overflow-y-auto divide-y divide-line/50">
            {list.isLoading && <p className="text-xs text-txt-2 py-8 text-center">Đang tải…</p>}
            {!list.isLoading && rows.length === 0 && (
              <p className="text-xs text-txt-2 py-8 text-center">Chưa có hội thoại nào.</p>
            )}
            {rows.map((c) => {
              const m = chMeta(c.channel); const s = statusChip(c)
              return (
                <button key={c.id} onClick={() => openConv(c.id)}
                  className={`w-full text-left px-3 py-2.5 flex gap-2.5 hover:bg-ink-3/40 ${sel === c.id ? 'bg-ink-3/70' : ''}`}>
                  <span className={`w-8 h-8 rounded-lg grid place-items-center shrink-0 ${m.cls}`}>{m.sym}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className={`font-semibold text-sm truncate flex-1 ${c.unread ? 'text-txt' : 'text-txt'}`}>
                        {c.customer_name || 'Khách ẩn danh'}
                      </span>
                      <span className="text-[10px] text-txt-2 shrink-0">{clock(c.last_message_at)}</span>
                      {c.unread > 0 && (
                        <span className="shrink-0 min-w-[18px] h-[18px] px-1 grid place-items-center rounded-full bg-flame text-white text-[10px] font-bold tabular-nums">
                          {c.unread}
                        </span>
                      )}
                    </span>
                    <span className={`block text-xs truncate mt-0.5 ${c.unread ? 'text-txt font-medium' : 'text-txt-2'}`}>
                      {c.last_preview || '—'}
                    </span>
                    <span className="flex items-center gap-1.5 mt-1.5">
                      <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border ${s.cls}`}>
                        {s.icon} {s.label}
                      </span>
                      {c.flagged && <Flag size={11} className="text-warn" />}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>
        </Card>

        {/* THREAD */}
        <Card className="p-0 overflow-hidden flex flex-col min-h-[480px]">
          {!sel && <div className="flex-1 grid place-items-center text-txt-2 text-sm">Chọn một hội thoại để xem.</div>}
          {sel && detail.isLoading && <div className="flex-1 grid place-items-center text-txt-2 text-sm">Đang tải…</div>}
          {conv && <Thread conv={conv} takeover={takeover} flag={flag} close={close}
            draft={draft} setDraft={setDraft} mode={mode} setMode={setMode} send={send} />}
        </Card>
      </div>
    </div>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function Thread({ conv, takeover, flag, close, draft, setDraft, mode, setMode, send }: any) {
  const c = conv as Conv
  const m = chMeta(c.channel)
  return (
    <>
      {/* Header hội thoại */}
      <div className="px-4 py-3 border-b border-line flex items-start gap-3 flex-wrap">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <span className={`w-9 h-9 rounded-lg grid place-items-center shrink-0 ${m.cls}`}>{m.sym}</span>
          <div className="min-w-0">
            <div className="font-semibold truncate">{c.customer_name || 'Khách ẩn danh'}</div>
            <div className="text-xs text-txt-2 flex items-center gap-1.5 min-w-0">
              <span className="shrink-0">{c.channel_display}</span>
              <span className="shrink-0" aria-hidden>·</span>
              <span className="inline-flex items-center gap-1 min-w-0">
                {c.owner_username
                  ? <><User size={11} className="shrink-0" /> <span className="truncate">{c.owner_username}</span></>
                  : <span className="truncate">chưa gán nhân viên</span>}
              </span>
              {c.customer_phone && <>
                <span className="shrink-0" aria-hidden>·</span>
                <span className="shrink-0 inline-flex items-center gap-1"><Phone size={11} />{c.customer_phone}</span>
              </>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0 ml-auto">
          <Button variant="ghost" size="sm" onClick={() => flag.mutate()} disabled={flag.isPending} title="Gắn cờ khách nóng">
            <Flag size={14} className={c.flagged ? 'text-warn' : ''} />
          </Button>
          {c.status !== 'closed' && (
            <Button variant="ghost" size="sm" onClick={() => close.mutate()} disabled={close.isPending}>
              <CheckCircle2 size={14} /> Đóng
            </Button>
          )}
          {c.status !== 'needs_human' && (
            <Button size="sm" onClick={() => takeover.mutate()} disabled={takeover.isPending}>
              <Hand size={14} /> Tiếp quản từ bot
            </Button>
          )}
          {c.status === 'needs_human' && (
            <span className="text-xs text-danger inline-flex items-center gap-1 px-2"><AlertCircle size={13} /> Đang xử lý tay</span>
          )}
        </div>
      </div>

      {/* Tin nhắn */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 max-h-[50vh]">
        {c.messages?.map((msg) => <Bubble key={msg.id} m={msg} />)}
      </div>

      {/* Quick reply */}
      {mode === 'reply' && (
        <div className="px-3 pt-2 flex flex-wrap gap-1.5">
          {QUICK_REPLIES.map((q) => (
            <button key={q} onClick={() => setDraft(q)}
              className="text-xs px-2.5 py-1 rounded-full border border-line text-txt-2 hover:text-flame hover:border-flame/40">
              {q}
            </button>
          ))}
        </div>
      )}

      {/* Ô nhập: trả lời khách / ghi chú nội bộ */}
      <div className="border-t border-line p-2.5">
        <div className="flex items-center gap-1 mb-1.5 text-xs">
          <button onClick={() => setMode('reply')}
            className={`px-2 py-0.5 rounded ${mode === 'reply' ? 'bg-flame/15 text-flame font-semibold' : 'text-txt-2'}`}>
            Trả lời khách
          </button>
          <button onClick={() => setMode('note')}
            className={`px-2 py-0.5 rounded inline-flex items-center gap-1 ${mode === 'note' ? 'bg-warn/15 text-warn font-semibold' : 'text-txt-2'}`}>
            <StickyNote size={11} /> Ghi chú nội bộ
          </button>
        </div>
        <div className="flex gap-2">
          <input value={draft} onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && draft.trim()) send.mutate() }}
            placeholder={mode === 'reply' ? `Trả lời qua ${c.channel_display}…` : 'Ghi chú nội bộ (khách không thấy)…'}
            className={`flex-1 bg-ink-3 border rounded-lg px-3.5 py-2 text-sm focus:outline-none ${mode === 'reply' ? 'border-line focus:border-flame' : 'border-warn/30 focus:border-warn'}`} />
          <Button onClick={() => send.mutate()} disabled={!draft.trim() || send.isPending}>
            <Send size={15} />
          </Button>
        </div>
        {mode === 'reply' && (
          <p className="text-[10px] text-txt-2 mt-1.5">
            Gửi tới khách qua {c.channel_display} cần webhook kênh; hiện lưu vào thread + tự tiếp quản.
          </p>
        )}
      </div>
    </>
  )
}

const MD = {
  strong: ({ children }: { children?: ReactNode }) => <strong className="font-semibold text-flame">{children}</strong>,
  p: ({ children }: { children?: ReactNode }) => <p className="m-0">{children}</p>,
  ul: ({ children }: { children?: ReactNode }) => <ul className="list-disc pl-4 my-1 space-y-0.5 marker:text-flame/60">{children}</ul>,
  ol: ({ children }: { children?: ReactNode }) => <ol className="list-decimal pl-4 my-1 space-y-0.5">{children}</ol>,
  li: ({ children }: { children?: ReactNode }) => <li>{children}</li>,
  h1: ({ children }: { children?: ReactNode }) => <h4 className="text-flame font-semibold mt-2 mb-0.5">{children}</h4>,
  h2: ({ children }: { children?: ReactNode }) => <h4 className="text-flame font-semibold mt-2 mb-0.5">{children}</h4>,
  h3: ({ children }: { children?: ReactNode }) => <h4 className="text-flame font-semibold mt-2 mb-0.5">{children}</h4>,
  code: ({ children }: { children?: ReactNode }) => <code className="font-mono text-[0.85em] bg-ink px-1 py-0.5 rounded">{children}</code>,
}

function agentName(m: Msg): string {
  if (m.intent?.startsWith('reply:')) return m.intent.slice(6)
  const mt = m.text.match(/^\[([^\]]+)\]/)
  return mt ? mt[1] : 'Nhân viên'
}

function Bubble({ m }: { m: Msg }) {
  // Khách: trái, xám.
  if (m.role === 'user') {
    return (
      <div className="flex gap-2.5">
        <div className="w-7 h-7 rounded-full grid place-items-center shrink-0 bg-ink-3 text-txt-2"><User size={14} /></div>
        <div className="max-w-[78%] rounded-2xl rounded-tl-sm bg-ink-3 text-txt px-3.5 py-2 text-sm whitespace-pre-wrap leading-relaxed">
          {m.text}
        </div>
      </div>
    )
  }
  // Nhân viên: phải, xanh lá + tên.
  if (m.role === 'agent') {
    const name = agentName(m)
    const body = m.text.replace(/^\[[^\]]+\]\s*/, '')
    return (
      <div className="flex gap-2.5 flex-row-reverse">
        <div className="w-7 h-7 rounded-full grid place-items-center shrink-0 bg-ok/15 text-ok"><User size={14} /></div>
        <div className="max-w-[80%]">
          <div className="text-[10px] text-ok mb-0.5 text-right">👩‍💼 {name}</div>
          <div className="rounded-2xl rounded-tr-sm bg-ok/10 border border-ok/20 text-txt px-3.5 py-2 text-sm whitespace-pre-wrap leading-relaxed">
            {body}
          </div>
        </div>
      </div>
    )
  }
  // Bot: phải, xanh dương + nhãn "Bot tự động", render markdown.
  return (
    <div className="flex gap-2.5 flex-row-reverse">
      <div className="w-7 h-7 rounded-full grid place-items-center shrink-0 bg-flame/15 text-flame"><Bot size={14} /></div>
      <div className="max-w-[86%]">
        <div className="flex justify-end items-center gap-1 text-[10px] text-blue-400 mb-0.5"><Bot size={11} /> Bot tự động</div>
        <div className="rounded-2xl rounded-tr-sm bg-blue-500/[0.08] border border-blue-500/20 text-txt px-3.5 py-2.5 text-[13.5px] leading-relaxed">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD}>{m.text}</ReactMarkdown>
        </div>
      </div>
    </div>
  )
}
