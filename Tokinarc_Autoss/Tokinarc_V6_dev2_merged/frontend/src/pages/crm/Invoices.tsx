/**
 * Tokinarc frontend — src/pages/crm/Invoices.tsx
 * Đề nghị xuất hóa đơn → đẩy sang MISA. GET /sales/invoices/,
 * GET /sales/invoices/export-misa/ (Excel), POST /{id}/mark-synced/.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, Download, CheckCircle2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { compactVnd } from '@/lib/crm'
import { isManager, useAuth } from '@/lib/auth/store'
import { PageHeader, Button, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'

interface Invoice {
  id: string; code: string; order_code: string; customer_name: string
  subtotal_vnd: string; tax_vnd: string; total_vnd: string
  misa_status: string; misa_ref: string; synced_at: string | null
}

export function InvoicesPage() {
  const qc = useQueryClient()
  const canSync = isManager(useAuth((s) => s.user?.role))
  const [busy, setBusy] = useState(false)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['invoices'],
    queryFn: async () => (await api.get<{ results: Invoice[] }>('/sales/invoices/')).data.results ?? [],
  })

  const exportMisa = async (all = false) => {
    setBusy(true)
    try {
      const res = await api.get(`/sales/invoices/export-misa/${all ? '?all=1' : ''}`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'hoadon_misa.xlsx'; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { toast.error(apiError(e)) } finally { setBusy(false) }
  }

  const markSynced = useMutation({
    mutationFn: (v: { id: string; ref: string }) =>
      api.post(`/sales/invoices/${v.id}/mark-synced/`, { misa_ref: v.ref }),
    onSuccess: () => { toast.success('Đã đánh dấu đồng bộ MISA'); qc.invalidateQueries({ queryKey: ['invoices'] }) },
    onError: (e) => toast.error(apiError(e)),
  })

  const pending = (data ?? []).filter((i) => i.misa_status === 'pending').length

  return (
    <div className="max-w-6xl">
      <PageHeader icon={<FileText size={20} className="text-flame" />} title="Hóa đơn (→ MISA)"
        subtitle={data ? `${data.length} đề nghị · ${pending} chờ đẩy MISA` : undefined}
        actions={
          <>
            <Button variant="ghost" onClick={() => exportMisa(false)} disabled={busy}>
              <Download size={14} /> Xuất MISA (chờ đẩy)
            </Button>
            <Button variant="ghost" onClick={() => exportMisa(true)} disabled={busy}>
              <Download size={14} /> Xuất tất cả
            </Button>
          </>
        } />

      <p className="text-xs text-txt-2 mb-3">
        Hóa đơn ở đây là <b>đề nghị xuất</b> — bấm “Xuất MISA” tải Excel để nạp vào MISA phát hành,
        rồi “Đánh dấu đồng bộ” + nhập số hóa đơn MISA.
      </p>

      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Mã</Th><Th>Khách hàng</Th><Th>Đơn</Th><Th className="text-right">Tiền hàng</Th>
          <Th className="text-right">Thuế</Th><Th className="text-right">Tổng</Th><Th>MISA</Th><Th />
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={8}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={8} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.length === 0 && <RowMsg colSpan={8}>Chưa có hóa đơn. Tạo từ Đơn bán (“Xuất hóa đơn”).</RowMsg>}
          {data?.map((i) => (
            <tr key={i.id} className="border-b border-line/50 last:border-0">
              <Td className="font-mono text-flame">{i.code}</Td>
              <Td className="font-medium">{i.customer_name}</Td>
              <Td className="font-mono text-xs text-txt-2">{i.order_code}</Td>
              <Td className="text-right tabular-nums">{compactVnd(i.subtotal_vnd)}</Td>
              <Td className="text-right tabular-nums text-txt-2">{compactVnd(i.tax_vnd)}</Td>
              <Td className="text-right tabular-nums font-medium">{compactVnd(i.total_vnd)}</Td>
              <Td>{i.misa_status === 'synced'
                ? <Tag tone="ok">MISA {i.misa_ref || '✓'}</Tag>
                : <Tag tone="warn">Chờ đẩy</Tag>}</Td>
              <Td className="text-right">
                {i.misa_status === 'pending' && canSync && (
                  <Button size="sm" variant="ghost"
                    onClick={() => {
                      const ref = window.prompt('Số hóa đơn MISA (nếu có):') ?? ''
                      markSynced.mutate({ id: i.id, ref })
                    }}>
                    <CheckCircle2 size={13} /> Đã đồng bộ
                  </Button>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </TableCard>
    </div>
  )
}
