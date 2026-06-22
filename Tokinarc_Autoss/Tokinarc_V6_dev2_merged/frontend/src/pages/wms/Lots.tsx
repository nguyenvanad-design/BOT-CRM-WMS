/**
 * Tokinarc frontend — src/pages/wms/Lots.tsx
 * Lô hàng (FEFO): danh sách lô còn tồn, cảnh báo lô sắp hết hạn.
 * GET /wms/lots/ (?expiring_days=N để lọc sắp hết hạn).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Boxes, AlertTriangle } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { formatDate } from '@/lib/crm'
import { PageHeader, Tag, Button, TableCard, Th, Td, RowMsg } from '@/components/ui'

interface Lot {
  id: string; lot_no: string; part: string | null; qty_remaining: number
  received_date: string; expires_at: string | null; bin: string | null
}

function expiryTone(exp: string | null): { label: string; tone: 'ok' | 'warn' | 'danger' | 'gray' } {
  if (!exp) return { label: '—', tone: 'gray' }
  const days = Math.ceil((new Date(exp).getTime() - Date.now()) / 86400000)
  if (days < 0) return { label: `Hết hạn ${formatDate(exp)}`, tone: 'danger' }
  if (days <= 30) return { label: `Còn ${days} ngày`, tone: 'warn' }
  return { label: formatDate(exp), tone: 'ok' }
}

export function WmsLotsPage() {
  const [onlyExpiring, setOnlyExpiring] = useState(false)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['wms-lots', onlyExpiring],
    queryFn: async () => {
      const params = onlyExpiring ? { expiring_days: 30 } : {}
      const r = await api.get<{ results: Lot[] }>('/wms/lots/', { params })
      return r.data.results ?? (r.data as unknown as Lot[])
    },
  })
  const lots = data ?? []

  return (
    <div className="max-w-4xl">
      <PageHeader icon={<Boxes size={20} className="text-flame" />} title="Lô hàng (FEFO)"
        subtitle={`${lots.length} lô còn tồn`}
        actions={
          <Button variant={onlyExpiring ? 'success' : 'ghost'} onClick={() => setOnlyExpiring((v) => !v)}>
            <AlertTriangle size={14} /> Sắp hết hạn (≤30 ngày)
          </Button>
        } />

      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Số lô</Th><Th>Mặt hàng</Th><Th>Ô</Th><Th className="text-right">Còn lại</Th>
          <Th>Nhập</Th><Th>Hạn dùng</Th>
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data && lots.length === 0 && <RowMsg colSpan={6}>Không có lô nào.</RowMsg>}
          {lots.map((l) => {
            const e = expiryTone(l.expires_at)
            return (
              <tr key={l.id} className="border-b border-line/50 last:border-0">
                <Td className="font-mono text-flame">{l.lot_no}</Td>
                <Td className="font-mono text-xs">{l.part || '—'}</Td>
                <Td className="font-mono text-xs">{l.bin || '—'}</Td>
                <Td className="text-right tabular-nums">{l.qty_remaining}</Td>
                <Td className="text-txt-2">{formatDate(l.received_date)}</Td>
                <Td><Tag tone={e.tone}>{e.label}</Tag></Td>
              </tr>
            )
          })}
        </tbody>
      </TableCard>
    </div>
  )
}
