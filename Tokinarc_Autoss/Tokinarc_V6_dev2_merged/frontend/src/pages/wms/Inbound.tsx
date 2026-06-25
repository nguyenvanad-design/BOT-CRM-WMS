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

export function InboundPage() {
  const qc = useQueryClient()
  const [formOpen, setFormOpen] = useState(false)
  const [scanId, setScanId] = useState<string | null>(null)
  const [viewOrder, setViewOrder] = useState<InboundOrder | null>(null)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['wms-inbound-list'],
    queryFn: () => fetchAll<InboundOrder>('/wms/inbound/'),
  })

  const confirm = useMutation({
    mutationFn: (v: { id: string; partial?: boolean }) =>
      api.post(`/wms/inbound/${v.id}/confirm/`, { partial: !!v.partial }),
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
                      onClick={() => confirm.mutate({ id: o.id, partial: true })}>
                      Nhận một phần
                    </Button>
                    <Button variant="success" size="sm"
                      disabled={confirm.isPending && confirm.variables?.id === o.id}
                      onClick={() => confirm.mutate({ id: o.id })}>
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
          <div className="text-sm text-txt-2">
            Trạng thái: <Tag tone={INBOUND_STATUS_TONE[viewOrder.status]}>{INBOUND_STATUS_LABEL[viewOrder.status]}</Tag>
          </div>
        )}
        q1Label="SL dự kiến" q2Label="Đã nhận"
        lines={(viewOrder?.lines ?? []).map((l, i) => ({
          key: l.id ?? String(i), name: l.part_name ?? '', code: l.part ?? l.torch ?? '—',
          q1: l.qty_expected, q2: l.qty_received,
        }))}
      />
    </div>
  )
}
