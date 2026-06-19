/**
 * Tokinarc frontend — src/pages/wms/ASN.tsx
 * ASN (báo trước hàng về) THẬT (GET /wms/asn/) + đánh dấu hàng đã về
 * (POST /wms/asn/{id}/arrive/ → tạo đơn nhập kho).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Inbox, Check, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import { formatDate } from '@/lib/crm'
import { Tag } from '@/components/ui'
import type { ASN } from '@/lib/types'
import {
  PageHeader, Button, TableCard, Th, Td, RowMsg,
} from '@/components/ui'
import { ASNForm } from '@/pages/wms/forms/ASNForm'

export function ASNPage() {
  const qc = useQueryClient()
  const [formOpen, setFormOpen] = useState(false)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['wms-asn-list'],
    queryFn: () => fetchAll<ASN>('/wms/asn/'),
  })

  const arrive = useMutation({
    mutationFn: (id: string) => api.post(`/wms/asn/${id}/arrive/`),
    onSuccess: () => {
      toast.success('Đã ghi nhận hàng về — tạo đơn nhập kho')
      qc.invalidateQueries({ queryKey: ['wms-asn-list'] })
      qc.invalidateQueries({ queryKey: ['wms-inbound-list'] })
      qc.invalidateQueries({ queryKey: ['wms'] })
    },
    onError: (e) => toast.error(apiError(e)),
  })

  const items = data?.items ?? []

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<Inbox size={20} className="text-flame" />} title="ASN — Báo hàng về"
        subtitle={data ? `${data.count} ASN` : undefined}
        actions={<Button onClick={() => setFormOpen(true)}><Plus size={14} /> Tạo ASN</Button>} />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Mã ASN</Th><Th>Nhà cung cấp</Th><Th>ETA</Th>
            <Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data && items.length === 0 && <RowMsg colSpan={5}>Chưa có ASN.</RowMsg>}
          {items.map((a) => (
            <tr key={a.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="font-mono text-flame">{a.code}</Td>
              <Td className="font-medium">{a.supplier || '—'}</Td>
              <Td className="text-txt-2">{formatDate(a.eta)}</Td>
              <Td>{a.is_arrived ? <Tag tone="ok">Đã về</Tag> : <Tag tone="warn">Chờ về</Tag>}</Td>
              <Td className="text-right">
                {!a.is_arrived ? (
                  <Button size="sm"
                    disabled={arrive.isPending && arrive.variables === a.id}
                    onClick={() => arrive.mutate(a.id)}>
                    <Check size={13} /> Đánh dấu về
                  </Button>
                ) : <span className="text-[11px] text-txt-2">—</span>}
              </Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      <ASNForm open={formOpen} onClose={() => setFormOpen(false)} />
    </div>
  )
}
