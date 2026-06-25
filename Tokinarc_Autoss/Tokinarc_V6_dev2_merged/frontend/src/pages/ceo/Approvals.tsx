/**
 * Tokinarc frontend — src/pages/ceo/Approvals.tsx
 * Trang DUYỆT TẬP TRUNG cho Manager/CEO: gom mọi báo giá đang chờ quyết định
 * vào một chỗ, thay vì phải mở từng trang.
 *   - GET  /crm/quotes/pending-approvals/   (manager+ thấy tất cả)
 *   - Cấp 1 → POST /crm/quotes/{id}/approve/      (manager/CEO/admin)
 *   - Cấp 2 → POST /crm/quotes/{id}/approve-l2/   (chỉ CEO/admin)
 *   - Từ chối → POST /crm/quotes/{id}/reject/      (manager+)
 * Đơn mua duyệt 2 cấp song song:
 *   - GET /purchasing/orders/pending-approvals/ + approve / approve-l2 / reject
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, Check, ShieldCheck, X, Eye, ShoppingCart, ScrollText } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { compactVnd, formatDate, QUOTE_STATUS_LABEL, QUOTE_STATUS_TONE } from '@/lib/crm'
import { useAuth, isManager, isCeo } from '@/lib/auth/store'
import type { Quote, Contract } from '@/lib/types'
import {
  PageHeader, Tag, Button, TableCard, Th, Td, Card,
} from '@/components/ui'
import { QuoteDetailModal } from '@/pages/crm/QuoteDetailModal'
import { PODetailModal, type PODetail } from '@/pages/purchasing/PODetailModal'
import { ContractDetailModal } from '@/pages/crm/ContractDetailModal'

const PO_TONE: Record<string, 'gray' | 'warn'> = { draft: 'gray', pending_ceo: 'warn' }
const HD_TONE: Record<string, 'gray' | 'warn'> = { draft: 'gray', pending_ceo: 'warn' }

export function ApprovalsPage() {
  const qc = useQueryClient()
  const role = useAuth((s) => s.user?.role)
  const canApprove = isManager(role)   // cấp 1
  const canApproveL2 = isCeo(role)     // cấp 2
  const [detail, setDetail] = useState<Quote | null>(null)
  const [poDetail, setPoDetail] = useState<PODetail | null>(null)
  const [hdDetail, setHdDetail] = useState<Contract | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['pending-approvals'],
    queryFn: async () => (await api.get<{ results: Quote[]; count: number }>(
      '/crm/quotes/pending-approvals/')).data,
  })
  const poData = useQuery({
    queryKey: ['pending-po-approvals'],
    queryFn: async () => (await api.get<{ results: PODetail[]; count: number }>(
      '/purchasing/orders/pending-approvals/')).data,
  })
  const hdData = useQuery({
    queryKey: ['pending-hd-approvals'],
    queryFn: async () => (await api.get<{ results: Contract[]; count: number }>(
      '/crm/contracts/pending-approvals/')).data,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['pending-approvals'] })
    qc.invalidateQueries({ queryKey: ['pending-po-approvals'] })
    qc.invalidateQueries({ queryKey: ['pending-hd-approvals'] })
    qc.invalidateQueries({ queryKey: ['quotes'] })
    qc.invalidateQueries({ queryKey: ['po'] })
    qc.invalidateQueries({ queryKey: ['contracts'] })
    qc.invalidateQueries({ queryKey: ['dash'] })
  }

  const hdApprove = useMutation({
    mutationFn: (id: string) => api.post(`/crm/contracts/${id}/approve/`),
    onSuccess: (res) => {
      toast.success(res.data.status === 'pending_ceo'
        ? 'Đã duyệt cấp 1 — chuyển CEO duyệt cấp 2' : 'Đã duyệt hợp đồng')
      invalidate()
    },
    onError: (e) => toast.error(apiError(e)),
  })
  const hdApproveL2 = useMutation({
    mutationFn: (id: string) => api.post(`/crm/contracts/${id}/approve-l2/`),
    onSuccess: () => { toast.success('CEO đã duyệt cấp 2'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const hdReject = useMutation({
    mutationFn: (v: { id: string; reason: string }) =>
      api.post(`/crm/contracts/${v.id}/reject/`, { reason: v.reason }),
    onSuccess: () => { toast.success('Đã từ chối hợp đồng'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const onHdReject = (id: string) => {
    const reason = window.prompt('Lý do từ chối hợp đồng?') ?? ''
    if (reason !== null) hdReject.mutate({ id, reason })
  }

  const poApprove = useMutation({
    mutationFn: (id: string) => api.post(`/purchasing/orders/${id}/approve/`),
    onSuccess: (res) => {
      toast.success(res.data.status === 'pending_ceo'
        ? 'Đã duyệt cấp 1 — chuyển CEO duyệt cấp 2' : 'Đã duyệt đơn mua')
      invalidate()
    },
    onError: (e) => toast.error(apiError(e)),
  })
  const poApproveL2 = useMutation({
    mutationFn: (id: string) => api.post(`/purchasing/orders/${id}/approve-l2/`),
    onSuccess: () => { toast.success('CEO đã duyệt cấp 2'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const poReject = useMutation({
    mutationFn: (v: { id: string; reason: string }) =>
      api.post(`/purchasing/orders/${v.id}/reject/`, { reason: v.reason }),
    onSuccess: () => { toast.success('Đã từ chối đơn mua'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const onPoReject = (id: string) => {
    const reason = window.prompt('Lý do từ chối đơn mua?') ?? ''
    if (reason !== null) poReject.mutate({ id, reason })
  }

  const approve = useMutation({
    mutationFn: (id: string) => api.post(`/crm/quotes/${id}/approve/`),
    onSuccess: (res) => {
      toast.success(res.data.status === 'pending_ceo'
        ? 'Đã duyệt cấp 1 — chuyển CEO duyệt cấp 2' : 'Đã duyệt báo giá')
      invalidate()
    },
    onError: (e) => toast.error(apiError(e)),
  })
  const approveL2 = useMutation({
    mutationFn: (id: string) => api.post(`/crm/quotes/${id}/approve-l2/`),
    onSuccess: () => { toast.success('CEO đã duyệt cấp 2'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const reject = useMutation({
    mutationFn: (v: { id: string; reason: string }) =>
      api.post(`/crm/quotes/${v.id}/reject/`, { reason: v.reason }),
    onSuccess: () => { toast.success('Đã từ chối báo giá'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })

  const all = data?.results ?? []
  const lvl1 = all.filter((q) => q.status === 'draft' || q.status === 'sent')
  const lvl2 = all.filter((q) => q.status === 'pending_ceo')

  const pos = poData.data?.results ?? []
  const poLvl1 = pos.filter((p) => p.status === 'draft')
  const poLvl2 = pos.filter((p) => p.status === 'pending_ceo')
  const hds = hdData.data?.results ?? []
  const hdLvl1 = hds.filter((h) => h.status === 'draft')
  const hdLvl2 = hds.filter((h) => h.status === 'pending_ceo')
  const totalPending = (data?.count ?? 0) + (poData.data?.count ?? 0) + (hdData.data?.count ?? 0)
  const nothingPending = all.length === 0 && pos.length === 0 && hds.length === 0

  const onReject = (id: string) => {
    const reason = window.prompt('Lý do từ chối báo giá?') ?? ''
    if (reason !== null) reject.mutate({ id, reason })
  }

  return (
    <div className="max-w-6xl">
      <PageHeader
        icon={<ClipboardCheck size={20} className="text-flame" />}
        title="Cần duyệt"
        subtitle={(data || poData.data) ? `${totalPending} mục đang chờ` : 'Hàng chờ duyệt tập trung'}
      />

      {isLoading && <Card>Đang tải…</Card>}
      {isError && <Card className="text-danger">Lỗi: {apiError(error)}</Card>}

      {!isLoading && !isError && nothingPending && (
        <Card className="text-txt-2">Không có mục nào đang chờ duyệt. 🎉</Card>
      )}

      {/* Báo giá vượt ngưỡng — chờ CEO duyệt cấp 2 (ưu tiên hiển thị trên) */}
      {lvl2.length > 0 && (
        <Section title="Chờ CEO duyệt (cấp 2)" count={lvl2.length}>
          {lvl2.map((q) => (
            <QuoteRow key={q.id} q={q}>
              <Button variant="ghost" size="sm" onClick={() => setDetail(q)}>
                <Eye size={13} /> Xem
              </Button>
              {canApproveL2 ? (
                <Button variant="success" size="sm"
                  disabled={approveL2.isPending && approveL2.variables === q.id}
                  onClick={() => approveL2.mutate(q.id)}>
                  <ShieldCheck size={13} /> Duyệt cấp 2 (CEO)
                </Button>
              ) : <span className="text-[11px] text-txt-2">Chờ CEO duyệt</span>}
              {canApprove && (
                <Button variant="ghost" size="sm"
                  disabled={reject.isPending && reject.variables?.id === q.id}
                  onClick={() => onReject(q.id)}>
                  <X size={13} /> Từ chối
                </Button>
              )}
            </QuoteRow>
          ))}
        </Section>
      )}

      {/* Báo giá chờ duyệt cấp 1 (manager+) */}
      {lvl1.length > 0 && (
        <Section title="Chờ duyệt cấp 1" count={lvl1.length}>
          {lvl1.map((q) => (
            <QuoteRow key={q.id} q={q}>
              <Button variant="ghost" size="sm" onClick={() => setDetail(q)}>
                <Eye size={13} /> Xem
              </Button>
              {canApprove ? (
                <Button variant="success" size="sm"
                  disabled={approve.isPending && approve.variables === q.id}
                  onClick={() => approve.mutate(q.id)}>
                  <Check size={13} /> Duyệt{q.requires_l2 ? ' (cấp 1)' : ''}
                </Button>
              ) : <span className="text-[11px] text-txt-2">Chờ duyệt</span>}
              {canApprove && (
                <Button variant="ghost" size="sm"
                  disabled={reject.isPending && reject.variables?.id === q.id}
                  onClick={() => onReject(q.id)}>
                  <X size={13} /> Từ chối
                </Button>
              )}
            </QuoteRow>
          ))}
        </Section>
      )}

      {/* ── Đơn mua chờ CEO duyệt cấp 2 ── */}
      {poLvl2.length > 0 && (
        <POSection title="Đơn mua — chờ CEO duyệt (cấp 2)" count={poLvl2.length}>
          {poLvl2.map((p) => (
            <PORow key={p.id} p={p}>
              <Button variant="ghost" size="sm" onClick={() => setPoDetail(p)}><Eye size={13} /> Xem</Button>
              {canApproveL2 ? (
                <Button variant="success" size="sm"
                  disabled={poApproveL2.isPending && poApproveL2.variables === p.id}
                  onClick={() => poApproveL2.mutate(p.id)}>
                  <ShieldCheck size={13} /> Duyệt cấp 2 (CEO)
                </Button>
              ) : <span className="text-[11px] text-txt-2">Chờ CEO duyệt</span>}
              {canApprove && (
                <Button variant="ghost" size="sm"
                  disabled={poReject.isPending && poReject.variables?.id === p.id}
                  onClick={() => onPoReject(p.id)}><X size={13} /> Từ chối</Button>
              )}
            </PORow>
          ))}
        </POSection>
      )}

      {/* ── Đơn mua chờ duyệt cấp 1 ── */}
      {poLvl1.length > 0 && (
        <POSection title="Đơn mua — chờ duyệt cấp 1" count={poLvl1.length}>
          {poLvl1.map((p) => (
            <PORow key={p.id} p={p}>
              <Button variant="ghost" size="sm" onClick={() => setPoDetail(p)}><Eye size={13} /> Xem</Button>
              {canApprove ? (
                <Button variant="success" size="sm"
                  disabled={poApprove.isPending && poApprove.variables === p.id}
                  onClick={() => poApprove.mutate(p.id)}>
                  <Check size={13} /> Duyệt
                </Button>
              ) : <span className="text-[11px] text-txt-2">Chờ duyệt</span>}
              {canApprove && (
                <Button variant="ghost" size="sm"
                  disabled={poReject.isPending && poReject.variables?.id === p.id}
                  onClick={() => onPoReject(p.id)}><X size={13} /> Từ chối</Button>
              )}
            </PORow>
          ))}
        </POSection>
      )}

      {/* ── Hợp đồng chờ CEO duyệt cấp 2 ── */}
      {hdLvl2.length > 0 && (
        <HDSection title="Hợp đồng — chờ CEO duyệt (cấp 2)" count={hdLvl2.length}>
          {hdLvl2.map((h) => (
            <HDRow key={h.id} h={h}>
              <Button variant="ghost" size="sm" onClick={() => setHdDetail(h)}><Eye size={13} /> Xem</Button>
              {canApproveL2 ? (
                <Button variant="success" size="sm"
                  disabled={hdApproveL2.isPending && hdApproveL2.variables === h.id}
                  onClick={() => hdApproveL2.mutate(h.id)}>
                  <ShieldCheck size={13} /> Duyệt cấp 2 (CEO)
                </Button>
              ) : <span className="text-[11px] text-txt-2">Chờ CEO duyệt</span>}
              {canApprove && (
                <Button variant="ghost" size="sm"
                  disabled={hdReject.isPending && hdReject.variables?.id === h.id}
                  onClick={() => onHdReject(h.id)}><X size={13} /> Từ chối</Button>
              )}
            </HDRow>
          ))}
        </HDSection>
      )}

      {/* ── Hợp đồng chờ duyệt cấp 1 ── */}
      {hdLvl1.length > 0 && (
        <HDSection title="Hợp đồng — chờ duyệt cấp 1" count={hdLvl1.length}>
          {hdLvl1.map((h) => (
            <HDRow key={h.id} h={h}>
              <Button variant="ghost" size="sm" onClick={() => setHdDetail(h)}><Eye size={13} /> Xem</Button>
              {canApprove ? (
                <Button variant="success" size="sm"
                  disabled={hdApprove.isPending && hdApprove.variables === h.id}
                  onClick={() => hdApprove.mutate(h.id)}>
                  <Check size={13} /> Duyệt
                </Button>
              ) : <span className="text-[11px] text-txt-2">Chờ duyệt</span>}
              {canApprove && (
                <Button variant="ghost" size="sm"
                  disabled={hdReject.isPending && hdReject.variables?.id === h.id}
                  onClick={() => onHdReject(h.id)}><X size={13} /> Từ chối</Button>
              )}
            </HDRow>
          ))}
        </HDSection>
      )}

      <QuoteDetailModal quote={detail} open={!!detail} onClose={() => setDetail(null)} />
      <PODetailModal po={poDetail} open={!!poDetail} onClose={() => setPoDetail(null)} />
      <ContractDetailModal contract={hdDetail} open={!!hdDetail} onClose={() => setHdDetail(null)} />
    </div>
  )
}

function HDSection({ title, count, children }: {
  title: string; count: number; children: React.ReactNode
}) {
  return (
    <div className="mb-5">
      <div className="text-sm font-semibold mb-2 flex items-center gap-2">
        <ScrollText size={15} className="text-flame" /> {title}
        <span className="bg-flame text-white rounded-full text-[10px] px-1.5 leading-4">{count}</span>
      </div>
      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Mã HĐ</Th><Th>Khách hàng</Th><Th className="text-right">Giá trị</Th>
            <Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </TableCard>
    </div>
  )
}

function HDRow({ h, children }: { h: Contract; children: React.ReactNode }) {
  return (
    <tr className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
      <Td className="font-mono text-flame">{h.code}</Td>
      <Td className="font-medium">{h.customer_name}</Td>
      <Td className="text-right tabular-nums">
        {compactVnd(h.value_vnd)}
        {Number(h.discount_pct) > 0 && <span className="text-warn text-[11px]"> · CK {h.discount_pct}%</span>}
      </Td>
      <Td><Tag tone={HD_TONE[h.status] ?? 'gray'}>{h.status_display}</Tag></Td>
      <Td className="text-right">
        <span className="inline-flex gap-1.5 justify-end">{children}</span>
      </Td>
    </tr>
  )
}

function POSection({ title, count, children }: {
  title: string; count: number; children: React.ReactNode
}) {
  return (
    <div className="mb-5">
      <div className="text-sm font-semibold mb-2 flex items-center gap-2">
        <ShoppingCart size={15} className="text-flame" /> {title}
        <span className="bg-flame text-white rounded-full text-[10px] px-1.5 leading-4">{count}</span>
      </div>
      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Mã PO</Th><Th>Nhà cung cấp</Th><Th className="text-right">Giá trị</Th>
            <Th>Kho</Th><Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </TableCard>
    </div>
  )
}

function PORow({ p, children }: { p: PODetail; children: React.ReactNode }) {
  return (
    <tr className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
      <Td className="font-mono text-flame">{p.code}</Td>
      <Td className="font-medium">{p.supplier_name}</Td>
      <Td className="text-right tabular-nums">{compactVnd(p.total_vnd)}</Td>
      <Td className="text-txt-2">{p.warehouse_code}</Td>
      <Td><Tag tone={PO_TONE[p.status] ?? 'gray'}>{p.status_display}</Tag></Td>
      <Td className="text-right">
        <span className="inline-flex gap-1.5 justify-end">{children}</span>
      </Td>
    </tr>
  )
}

function Section({ title, count, children }: {
  title: string; count: number; children: React.ReactNode
}) {
  return (
    <div className="mb-5">
      <div className="text-sm font-semibold mb-2 flex items-center gap-2">
        {title}
        <span className="bg-flame text-white rounded-full text-[10px] px-1.5 leading-4">{count}</span>
      </div>
      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Mã BG</Th><Th>Khách hàng</Th><Th className="text-right">Giá trị</Th>
            <Th>Hạn</Th><Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </TableCard>
    </div>
  )
}

function QuoteRow({ q, children }: { q: Quote; children: React.ReactNode }) {
  return (
    <tr className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
      <Td className="font-mono text-flame">{q.code}</Td>
      <Td className="font-medium">{q.customer_name}</Td>
      <Td className="text-right tabular-nums">
        {compactVnd(q.total_vnd)}
        {Number(q.discount_pct) > 0 && <span className="text-warn text-[11px]"> · CK {q.discount_pct}%</span>}
      </Td>
      <Td className="text-txt-2">{formatDate(q.due_date)}</Td>
      <Td><Tag tone={QUOTE_STATUS_TONE[q.status]}>{QUOTE_STATUS_LABEL[q.status]}</Tag></Td>
      <Td className="text-right">
        <span className="inline-flex gap-1.5 justify-end">{children}</span>
      </Td>
    </tr>
  )
}
