/**
 * Tokinarc frontend — src/pages/crm/MyActivity.tsx
 * Nhật ký hoạt động: gộp Visit/Hoạt động/Lead/Báo giá/Đơn/Ticket của sale theo ngày.
 * GET /crm/my-activity/?days=&owner=  (sale → của mình; manager → cả team, lọc owner).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  CalendarDays, MapPin, Phone, Radar, FileText, ShoppingCart, Ticket as TicketIcon,
} from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { compactVnd } from '@/lib/crm'
import { isManager, useAuth } from '@/lib/auth/store'
import { PageHeader, Tag } from '@/components/ui'

interface Ev {
  date: string; kind: string; title: string; customer?: string; detail?: string
  amount_vnd?: number; status?: string; who?: string; link?: string
}
const KIND: Record<string, { icon: typeof MapPin; label: string; tone: 'blue' | 'purple' | 'flame' | 'ok' | 'warn' | 'gray' }> = {
  visit: { icon: MapPin, label: 'Gặp khách', tone: 'purple' },
  activity: { icon: Phone, label: 'Liên hệ', tone: 'blue' },
  lead: { icon: Radar, label: 'Lead', tone: 'flame' },
  quote: { icon: FileText, label: 'Báo giá', tone: 'warn' },
  order: { icon: ShoppingCart, label: 'Đơn bán', tone: 'ok' },
  ticket: { icon: TicketIcon, label: 'Ticket', tone: 'gray' },
}
const dayKey = (iso: string) => iso.slice(0, 10)
const dayLabel = (k: string) => {
  const today = new Date().toISOString().slice(0, 10)
  const y = new Date(Date.now() - 864e5).toISOString().slice(0, 10)
  if (k === today) return 'Hôm nay'
  if (k === y) return 'Hôm qua'
  const [yy, mm, dd] = k.split('-')
  return `${dd}/${mm}/${yy}`
}

export function MyActivityPage() {
  const role = useAuth((s) => s.user?.role)
  const mgr = isManager(role)
  const nav = useNavigate()
  const [days, setDays] = useState(7)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['my-activity', days],
    queryFn: async () => (await api.get<{ results: Ev[]; count: number }>(`/crm/my-activity/?days=${days}`)).data,
  })

  const groups: Record<string, Ev[]> = {}
  for (const e of data?.results ?? []) (groups[dayKey(e.date)] ||= []).push(e)
  const dayKeys = Object.keys(groups).sort().reverse()

  return (
    <div className="max-w-3xl">
      <PageHeader icon={<CalendarDays size={20} className="text-flame" />}
        title={mgr ? 'Nhật ký hoạt động (team)' : 'Nhật ký của tôi'}
        subtitle={data ? `${data.count} hoạt động · ${days} ngày` : undefined}
        actions={
          <div className="flex gap-1">
            {[7, 30, 90].map((d) => (
              <button key={d} onClick={() => setDays(d)}
                className={`text-xs rounded-md px-2.5 py-1.5 border transition-colors ${
                  days === d ? 'border-flame text-flame bg-flame/10' : 'border-line text-txt-2 hover:text-txt'}`}>
                {d} ngày
              </button>
            ))}
          </div>
        } />

      {isLoading && <div className="text-txt-2 text-sm">Đang tải…</div>}
      {isError && <div className="text-danger text-sm">Lỗi: {apiError(error)}</div>}
      {data && data.count === 0 && (
        <div className="text-txt-2 text-sm border border-line rounded-lg p-6 text-center">
          Chưa có hoạt động trong {days} ngày qua.
        </div>
      )}

      <div className="space-y-5">
        {dayKeys.map((dk) => (
          <div key={dk}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-semibold">{dayLabel(dk)}</span>
              <span className="text-[11px] text-txt-2">· {groups[dk].length} việc</span>
              <div className="flex-1 h-px bg-line" />
            </div>
            <div className="space-y-1.5">
              {groups[dk].map((e, i) => {
                const k = KIND[e.kind] ?? KIND.activity
                const Icon = k.icon
                return (
                  <div key={i} onClick={() => e.link && nav(e.link)}
                    className="flex items-start gap-3 bg-ink-2 border border-line rounded-lg px-3 py-2.5
                               hover:border-flame/40 cursor-pointer transition-colors">
                    <div className="mt-0.5"><Icon size={15} className="text-txt-2" /></div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Tag tone={k.tone}>{k.label}</Tag>
                        <span className="text-sm font-medium truncate">{e.title}</span>
                        {typeof e.amount_vnd === 'number' && e.amount_vnd > 0 && (
                          <span className="text-xs tabular-nums text-flame">{compactVnd(e.amount_vnd)}</span>
                        )}
                      </div>
                      {(e.customer || e.detail) && (
                        <div className="text-xs text-txt-2 truncate mt-0.5">
                          {e.customer && <span className="text-txt">{e.customer}</span>}
                          {e.customer && e.detail ? ' — ' : ''}{e.detail}
                        </div>
                      )}
                    </div>
                    {mgr && e.who && <span className="text-[11px] text-txt-2 shrink-0">{e.who}</span>}
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
