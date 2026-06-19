/**
 * Tokinarc frontend — src/pages/wms/Inbound.tsx
 * Đơn nhập kho THẬT (GET /wms/inbound/) + xác nhận nhận hàng
 * (POST /wms/inbound/{id}/confirm/ → cộng tồn theo từng line).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PackageCheck, Check, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import { formatDate } from '@/lib/crm'
import { INBOUND_STATUS_LABEL, INBOUND_STATUS_TONE } from '@/lib/wms'
import type { InboundOrder } from '@/lib/types'
import {
  PageHeader, Tag, Button, TableCard, Th, Td, RowMsg,
} from '@/components/ui'
import { InboundForm } from '@/pages/wms/forms/InboundForm'

export function InboundPage() {
  const qc = useQueryClient()
  const [formOpen, setFormOpen] = useState(false)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['wms-inbound-list'],
    queryFn: () => fetchAll<InboundOrder>('/wms/inbound/'),
  })

  const confirm = useMutation({
    mutationFn: (id: string) => api.post(`/wms/inbound/${id}/confirm/`),
    onSuccess: () => {
      toast.success('Đã xác nhận nhận hàng — tồn kho đã cộng')
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
                {(o.status === 'draft' || o.status === 'confirmed') ? (
                  <Button variant="success" size="sm"
                    disabled={confirm.isPending && confirm.variables === o.id}
                    onClick={() => confirm.mutate(o.id)}>
                    <Check size={13} /> Xác nhận nhận
                  </Button>
                ) : <span className="text-[11px] text-txt-2">—</span>}
              </Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      <InboundForm open={formOpen} onClose={() => setFormOpen(false)} />
    </div>
  )
}
