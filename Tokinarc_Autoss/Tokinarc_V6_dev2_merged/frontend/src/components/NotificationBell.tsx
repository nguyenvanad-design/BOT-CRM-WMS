/**
 * Tokinarc frontend — src/components/NotificationBell.tsx
 * Chuông thông báo: badge số chưa đọc (poll 30s) + dropdown danh sách, bấm để
 * đến link + đánh dấu đã đọc. Nguồn: /api/v1/notifications/.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCheck } from 'lucide-react'
import { api } from '@/lib/api'

interface Notif { id: string; kind: string; message: string; link: string; is_read: boolean; created_at: string }

export function NotificationBell() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [open, setOpen] = useState(false)

  const unread = useQuery({
    queryKey: ['notif', 'unread'],
    queryFn: async () => (await api.get<{ count: number }>('/notifications/unread/')).data.count,
    refetchInterval: 30000,
  })
  const list = useQuery({
    queryKey: ['notif', 'list'],
    queryFn: async () => (await api.get<{ results: Notif[] }>('/notifications/')).data.results ?? [],
    enabled: open,
  })
  const readAll = useMutation({
    mutationFn: () => api.post('/notifications/read-all/'),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['notif'] }) },
  })
  const readOne = useMutation({
    mutationFn: (id: string) => api.post(`/notifications/${id}/read/`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['notif'] }) },
  })

  const count = unread.data ?? 0

  return (
    <div className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-label="Thông báo"
        className="relative text-txt-2 hover:text-txt p-1.5 rounded-md hover:bg-ink-3 transition-colors">
        <Bell size={18} />
        {count > 0 && (
          <span className="absolute -top-0.5 -right-0.5 bg-flame text-white text-[10px] font-bold
                           rounded-full min-w-[16px] h-4 px-1 grid place-items-center">
            {count > 9 ? '9+' : count}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-2 w-80 max-h-96 overflow-y-auto bg-ink-2 border border-line
                          rounded-lg shadow-xl z-40">
            <div className="flex items-center justify-between px-3 py-2 border-b border-line">
              <span className="text-sm font-semibold">Thông báo</span>
              <button onClick={() => readAll.mutate()} disabled={count === 0}
                className="text-[11px] text-txt-2 hover:text-flame flex items-center gap-1 disabled:opacity-40">
                <CheckCheck size={13} /> Đọc hết
              </button>
            </div>
            {list.isLoading && <p className="text-xs text-txt-2 py-6 text-center">Đang tải…</p>}
            {list.data && list.data.length === 0 && (
              <p className="text-xs text-txt-2 py-6 text-center">Chưa có thông báo.</p>
            )}
            {list.data?.map((n) => (
              <button key={n.id}
                onClick={() => { readOne.mutate(n.id); if (n.link) nav(n.link); setOpen(false) }}
                className={`w-full text-left px-3 py-2.5 border-b border-line/50 last:border-0 hover:bg-ink-3
                            ${n.is_read ? 'opacity-60' : ''}`}>
                <div className="flex items-start gap-2">
                  {!n.is_read && <span className="mt-1 w-2 h-2 rounded-full bg-flame shrink-0" />}
                  <div className="min-w-0">
                    <p className="text-sm leading-snug">{n.message}</p>
                    <p className="text-[10px] text-txt-2 mt-0.5">{new Date(n.created_at).toLocaleString('vi-VN')}</p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
