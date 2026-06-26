/**
 * Tokinarc frontend — src/pages/wms/Inbound.tsx
 * Đơn nhập kho THẬT (GET /wms/inbound/) + xác nhận nhận hàng
 * (POST /wms/inbound/{id}/confirm/ → cộng tồn theo từng line).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PackageCheck, Check, Plus, ScanLine, Eye, Download } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { downloadFile } from '@/lib/download'
import { fetchAll } from '@/lib/list'
import { formatDate } from '@/lib/crm'
import { INBOUND_STATUS_LABEL, INBOUND_STATUS_TONE } from '@/lib/wms'
import type { InboundOrder } from '@/lib/types'
import {
  PageHeader, Tag, Button, TableCard, Th, Td, RowMsg,
} from '@/components/ui'
import { InboundForm } from '@/pages/wms/forms/InboundForm'
import { ScanOrderModal } from '@/pages/wms/ScanOrderModal'
import { OrderLinesModal } from '@/pages/wms/OrderLinesModal'
import { Modal } from '@/components/Modal'

export function InboundPage() {
  const qc = useQueryClient()
  const [formOpen, setFormOpen] = useState(false)
  const [scanId, setScanId] = useState<string | null>(null)
  const [viewOrder, setViewOrder] = useState<InboundOrder | null>(null)
  const [partialFor, setPartialFor] = useState<InboundOrder | null>(null)   // phiếu đang nhận một phần
  const [reason, setReason] = useState('')
  const [fullFor, setFullFor] = useState<InboundOrder | null>(null)   // xác nhận nhận đủ khi chưa quét
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['wms-inbound-list'],
    queryFn: () => fetchAll<InboundOrder>('/wms/inbound/'),
  })

  const confirm = useMutation({
    mutationFn: (v: { id: string; partial?: boolean; shortage_note?: string }) =>
      api.post(`/wms/inbound/${v.id}/confirm/`, { partial: !!v.partial, shortage_note: v.shortage_note ?? '' }),
    onSuccess: (r) => {
      toast.success(r.data?.status === 'partial'
        ? 'Đã nhận một phần — phiếu còn mở, nhận tiếp khi hàng về'
        : 'Đã xác nhận nhận hàng — tồn kho đã cộng')
      qc.invalidateQueries({ queryKey: ['wms-inbound-list'] })
      qc.invalidateQueries({ queryKey: ['wms'] })
      qc.invalidateQueries({ queryKey: ['wms-inventory'] })
    },
    onError: (e) => toast.error(apiError(e)),
  })

  const items = data?.items ?? []

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<PackageCheck size={20} className="text-flame" />} title="Nhập kho"
        subtitle={data ? `${data.count} đơn nhập` : undefined}
        actions={<Button onClick={() => setFormOpen(true)}><Plus size={14} /> Tạo đơn nhập</Button>} />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Mã đơn</Th><Th className="text-right">Số dòng</Th><Th>Nhận lúc</Th>
            <Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data && items.length === 0 && <RowMsg colSpan={5}>Chưa có đơn nhập.</RowMsg>}
          {items.map((o) => (
            <tr key={o.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="font-mono text-flame">{o.code}</Td>
              <Td className="text-right tabular-nums">{o.lines?.length ?? 0}</Td>
              <Td className="text-txt-2">{formatDate(o.received_at)}</Td>
              <Td><Tag tone={INBOUND_STATUS_TONE[o.status]}>{INBOUND_STATUS_LABEL[o.status]}</Tag></Td>
              <Td className="text-right">
                <span className="inline-flex gap-1.5 items-center">
                <Button variant="ghost" size="sm" onClick={() => setViewOrder(o)}>
                  <Eye size={13} /> Xem
                </Button>
                <Button variant="ghost" size="sm"
                  onClick={() => downloadFile(`/wms/inbound/${o.id}/export-xlsx/`, `phieu_nhap_${o.code}.xlsx`)}>
                  <Download size={13} /> Excel
                </Button>
                {(o.status === 'draft' || o.status === 'confirmed' || o.status === 'partial') ? (
                  <span className="inline-flex gap-1.5">
                    <Button variant="ghost" size="sm" onClick={() => setScanId(o.id)}>
                      <ScanLine size={13} /> Quét
                    </Button>
                    <Button variant="ghost" size="sm"
                      disabled={confirm.isPending && confirm.variables?.id === o.id}
                      onClick={() => { setReason(o.shortage_note ?? ''); setPartialFor(o) }}>
                      Nhận một phần
                    </Button>
                    <Button variant="success" size="sm"
                      disabled={confirm.isPending && confirm.variables?.id === o.id}
                      onClick={() => {
                        const scanned = (o.lines ?? []).some((l) => (l.qty_received ?? 0) > 0)
                        if (scanned) confirm.mutate({ id: o.id })   // đã quét → nhận thẳng
                        else setFullFor(o)                          // chưa quét → hỏi xác nhận
                      }}>
                      <Check size={13} /> Nhận đủ
                    </Button>
                  </span>
                ) : null}
                </span>
              </Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      <InboundForm open={formOpen} onClose={() => setFormOpen(false)} />
      <ScanOrderModal open={!!scanId} onClose={() => setScanId(null)} kind="inbound" orderId={scanId} />
      <OrderLinesModal
        open={!!viewOrder} onClose={() => setViewOrder(null)}
        title={`Phiếu nhập ${viewOrder?.code ?? ''}`}
        meta={viewOrder && (
          <div className="text-sm text-txt-2 space-y-1.5">
            <div>
              Trạng thái: <Tag tone={INBOUND_STATUS_TONE[viewOrder.status]}>{INBOUND_STATUS_LABEL[viewOrder.status]}</Tag>
              {viewOrder.po_code && <span className="ml-3">Từ đơn mua: <b className="text-txt font-mono">{viewOrder.po_code}</b></span>}
            </div>
            {viewOrder.shortage_note && (
              <div className="bg-danger/10 border border-danger/30 rounded-md px-3 py-2 text-txt">
                <b className="text-danger">Lý do nhận thiếu:</b> {viewOrder.shortage_note}
              </div>
            )}
          </div>
        )}
        q1Label="SL dự kiến" q2Label="Đã nhận"
        lines={(viewOrder?.lines ?? []).map((l, i) => ({
          key: l.id ?? String(i), name: l.part_name ?? '', code: l.part ?? l.torch ?? '—',
          q1: l.qty_expected, q2: l.qty_received,
        }))}
      />

      {/* Modal nhận một phần — nhập lý do thiếu */}
      <Modal open={!!partialFor} onClose={() => setPartialFor(null)}
        title={`Nhận một phần — ${partialFor?.code ?? ''}`}
        icon={<PackageCheck size={18} className="text-flame" />}
        footer={
          <>
            <Button variant="ghost" onClick={() => setPartialFor(null)}>Hủy</Button>
            <Button disabled={confirm.isPending}
              onClick={() => partialFor && confirm.mutate(
                { id: partialFor.id, partial: true, shortage_note: reason },
                { onSuccess: () => setPartialFor(null) })}>
              {confirm.isPending ? 'Đang lưu…' : 'Xác nhận nhận một phần'}
            </Button>
          </>
        }>
        <div className="space-y-2">
          <p className="text-sm text-txt-2">
            Cộng tồn phần đã quét/nhận; phần còn thiếu giữ phiếu <b>mở</b> để nhận tiếp khi hàng về.
          </p>
          <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold">Lý do nhận thiếu</label>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} autoFocus
            placeholder="VD: NCC giao thiếu 20 cái, hẹn giao bù tuần sau / hàng lỗi 2 cái…"
            className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm focus:border-flame focus:outline-none" />
        </div>
      </Modal>

      {/* Xác nhận "Nhận đủ" khi CHƯA quét món nào */}
      <Modal open={!!fullFor} onClose={() => setFullFor(null)}
        title={`Nhận đủ — ${fullFor?.code ?? ''}`}
        icon={<Check size={18} className="text-flame" />}
        footer={
          <>
            <Button variant="ghost" onClick={() => setFullFor(null)}>Hủy</Button>
            <Button variant="success" disabled={confirm.isPending}
              onClick={() => fullFor && confirm.mutate({ id: fullFor.id },
                { onSuccess: () => setFullFor(null) })}>
              {confirm.isPending ? 'Đang lưu…' : 'Vẫn nhận đủ'}
            </Button>
          </>
        }>
        <p className="text-sm text-txt">
          Bạn <b className="text-warn">chưa quét/nhận món nào</b>. Nếu xác nhận, hệ thống coi như
          nhận <b>ĐỦ theo số lượng đặt</b> mà không kiểm tra thực tế. Nên <b>Quét</b> từng món
          trước để đối chiếu.
        </p>
      </Modal>
    </div>
  )
}
