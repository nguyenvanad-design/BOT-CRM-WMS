/**
 * Tokinarc frontend — src/pages/crm/Pipeline.tsx
 * Kanban cơ hội TỰ ĐỘNG — KHÔNG kéo thả. Thẻ tiến giai đoạn theo SỰ KIỆN THẬT:
 *   ghi nhận gặp/gọi (gắn deal) → Thẩm định · tạo Báo giá → Đề xuất ·
 *   báo giá được duyệt → Đàm phán · báo giá thành Đơn/HĐ → Thắng.
 * Thua = nút "Đánh dấu thua" (bắt buộc chọn lý do — win/loss analysis).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Filter, XCircle, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import { compactVnd, OPP_STAGE_LABEL, OPP_STAGE_TONE, OPP_STAGE_ORDER, OPP_LOST_REASONS } from '@/lib/crm'
import type { Opportunity } from '@/lib/types'
import { PageHeader, Tag, Button } from '@/components/ui'
import { Modal } from '@/components/Modal'

// Chú giải sự kiện đẩy thẻ — hiện dưới tên cột để sale biết "làm gì thì thẻ tự chạy".
const STAGE_HINT: Record<string, string> = {
  prospect: 'Deal mới từ lead',
  qualify: 'Tự vào khi ghi nhận gặp/gọi',
  proposal: 'Tự vào khi tạo báo giá',
  negotiate: 'Tự vào khi báo giá được duyệt',
  won: 'Tự vào khi tạo đơn/hợp đồng',
  lost: 'Bấm "Thua…" trên thẻ + lý do',
}

export function PipelinePage({ embedded = false }: { embedded?: boolean }) {
  const qc = useQueryClient()
  const [losing, setLosing] = useState<Opportunity | null>(null)   // deal đang đánh dấu thua
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['pipeline'],
    queryFn: () => fetchAll<Opportunity>('/crm/opportunities/'),
    refetchInterval: 15000,   // thẻ TỰ chạy theo sự kiện → poll để thấy cập nhật
  })

  const markLost = useMutation({
    mutationFn: (v: { id: string; reason: string; note: string }) =>
      api.post(`/crm/opportunities/${v.id}/mark-lost/`, { reason: v.reason, note: v.note }),
    onSuccess: () => {
      toast.success('Đã đánh dấu THUA — deal rời khỏi dự báo')
      setLosing(null); setReason(''); setNote('')
      qc.invalidateQueries({ queryKey: ['pipeline'] })
      qc.invalidateQueries({ queryKey: ['opportunities'] })
      qc.invalidateQueries({ queryKey: ['dash'] })
    },
    onError: (e) => toast.error(apiError(e)),
  })

  const items = data?.items ?? []

  if (isLoading) return <Shell embedded={embedded}><p className="text-txt-2 text-sm">Đang tải…</p></Shell>
  if (isError) return <Shell embedded={embedded}><p className="text-danger text-sm">Lỗi: {apiError(error)}</p></Shell>

  return (
    <Shell embedded={embedded}>
      <div className="flex gap-3 overflow-x-auto pb-2">
        {OPP_STAGE_ORDER.map((stage) => {
          const col = items.filter((o) => o.stage === stage)
          const sum = col.reduce((s, o) => s + Number(o.est_value_vnd || 0), 0)
          return (
            <div key={stage}
              className="min-w-[220px] w-[220px] bg-ink-2 border border-line rounded-lg p-3 shrink-0">
              <div className="flex items-center justify-between mb-1">
                <Tag tone={OPP_STAGE_TONE[stage]}>{OPP_STAGE_LABEL[stage]}</Tag>
                <span className="text-[11px] text-txt-2">{col.length}</span>
              </div>
              <div className="text-[11px] text-txt-2 tabular-nums">{compactVnd(sum)}</div>
              <div className="text-[10px] text-txt-2/60 mb-2 leading-tight">{STAGE_HINT[stage]}</div>
              <div className="space-y-2">
                {col.map((o) => (
                  <div key={o.id}
                    className="bg-ink-3 border border-transparent hover:border-line rounded-md p-2.5 transition-colors">
                    <div className="text-xs font-semibold leading-tight">{o.title}</div>
                    <div className="text-[11px] text-flame mt-1 tabular-nums">{compactVnd(o.est_value_vnd)}</div>
                    <div className="text-[10px] text-txt-2 mt-1">{o.customer_name} · {o.probability}%</div>
                    {stage === 'lost' && o.lost_reason && (
                      <div className="mt-1.5 text-[10px] text-danger/90 bg-danger/10 border border-danger/20 rounded px-1.5 py-0.5">
                        {o.lost_reason_display}{o.lost_note ? ` — ${o.lost_note}` : ''}
                      </div>
                    )}
                    {stage !== 'won' && stage !== 'lost' && (
                      <button
                        onClick={() => { setLosing(o); setReason(''); setNote('') }}
                        className="mt-1.5 text-[10px] text-txt-2 hover:text-danger inline-flex items-center gap-1">
                        <XCircle size={11} /> Thua…
                      </button>
                    )}
                  </div>
                ))}
                {col.length === 0 && (
                  <div className="text-[11px] text-txt-2/60 text-center py-4 border border-dashed border-line rounded-md">
                    Chưa có deal
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Modal đánh dấu THUA — bắt buộc lý do */}
      <Modal open={!!losing} onClose={() => setLosing(null)}
        title={`Đánh dấu THUA — ${losing?.title ?? ''}`}
        icon={<XCircle size={18} className="text-danger" />}
        footer={
          <>
            <Button variant="ghost" onClick={() => setLosing(null)}>Hủy</Button>
            <Button variant="danger" disabled={!reason || markLost.isPending}
              onClick={() => losing && markLost.mutate({ id: losing.id, reason, note })}>
              {markLost.isPending ? 'Đang lưu…' : 'Xác nhận THUA'}
            </Button>
          </>
        }>
        <div className="space-y-3">
          <p className="text-sm text-txt-2">
            Deal sẽ rời khỏi dự báo doanh thu. <b className="text-txt">Lý do thua là bắt buộc</b> —
            dữ liệu này giúp công ty biết mình thua vì gì nhiều nhất.
          </p>
          <div>
            <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">Lý do thua *</label>
            <div className="grid grid-cols-2 gap-1.5">
              {OPP_LOST_REASONS.map((r) => (
                <button key={r.value} onClick={() => setReason(r.value)}
                  className={`text-left text-sm px-3 py-2 rounded-md border transition-colors ${
                    reason === r.value ? 'border-danger bg-danger/10 text-txt' : 'border-line text-txt-2 hover:border-danger/40'}`}>
                  {r.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">Ghi chú thêm</label>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
              placeholder="VD: đối thủ chào rẻ hơn 12%, khách hẹn quay lại Q4…"
              className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm focus:border-danger focus:outline-none" />
          </div>
        </div>
      </Modal>
    </Shell>
  )
}

function Shell({ children, embedded }: { children: React.ReactNode; embedded?: boolean }) {
  return (
    <div>
      {!embedded && (
        <PageHeader
          icon={<Filter size={20} className="text-flame" />}
          title="Pipeline"
          subtitle={<span className="inline-flex items-center gap-1">
            <Zap size={12} className="text-flame" /> Kanban tự động — thẻ tự chạy theo ghi nhận
            gặp/gọi, báo giá, duyệt, tạo đơn (không kéo thả)</span>}
        />
      )}
      {children}
    </div>
  )
}
