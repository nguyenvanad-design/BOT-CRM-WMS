/**
 * Tokinarc frontend — src/pages/ceo/Inventory.tsx
 * Tồn kho cấp điều hành: giá trị tồn, theo chi nhánh kho, hàng sắp hết.
 * Số liệu THẬT: /analytics/inventory/value (toàn + theo kho) + /wms/inventory.
 */
import { useQuery, useQueries } from '@tanstack/react-query'
import { Package } from 'lucide-react'
import { getInventoryValue } from '@/lib/analytics'
import { fetchAll, fetchPage } from '@/lib/list'
import { apiError } from '@/lib/api'
import { compactVnd } from '@/lib/crm'
import type { Warehouse, InventoryItem } from '@/lib/types'
import { Card, SectionTitle, StatCard, PageHeader, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'

export function CeoInventoryPage() {
  const total = useQuery({ queryKey: ['ceo', 'invv', 'all'], queryFn: () => getInventoryValue() })
  const whs = useQuery({ queryKey: ['ceo', 'whs'], queryFn: () => fetchAll<Warehouse>('/wms/warehouses/') })
  const low = useQuery({
    queryKey: ['ceo', 'low'],
    queryFn: () => fetchPage<InventoryItem>('/wms/inventory/', { low_stock: 'true', page: 1 }),
  })

  // Giá trị tồn theo từng kho (gọi inventory/value?warehouse= cho mỗi kho)
  const warehouses = whs.data?.items ?? []
  const perWh = useQueries({
    queries: warehouses.map((w) => ({
      queryKey: ['ceo', 'invv', w.code],
      queryFn: () => getInventoryValue(w.code),
      enabled: warehouses.length > 0,
    })),
  })
  const branchRows = warehouses.map((w, i) => ({
    code: w.code, name: w.name, value: Number(perWh[i]?.data?.inventory_value_vnd ?? 0),
  }))
  const maxBranch = Math.max(1, ...branchRows.map((b) => b.value))

  return (
    <div className="max-w-6xl">
      <PageHeader icon={<Package size={20} className="text-flame" />} title="Tồn kho"
        subtitle="Tổng quan tồn kho cấp điều hành" />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Giá trị tồn kho" tone="flame"
          value={total.isLoading ? '…' : compactVnd(total.data?.inventory_value_vnd)}
          delta={total.data ? <span className="text-txt-2">{total.data.sku_count} SKU</span> : undefined} />
        <StatCard label="Số kho" tone="blue" value={whs.isLoading ? '…' : warehouses.length} />
        <StatCard label="Sắp hết hàng" tone="danger" value={low.isLoading ? '…' : (low.data?.count ?? 0)}
          delta={<span className="text-txt-2">SKU cần đặt</span>} />
        <StatCard label="Dòng tồn (SKU×bin)" tone="txt"
          value={total.isLoading ? '…' : (total.data?.sku_count ?? 0)} />
      </div>

      <Card className="mb-4">
        <SectionTitle>Tồn kho theo chi nhánh</SectionTitle>
        {whs.isLoading && <p className="text-txt-2 text-sm py-6 text-center">Đang tải…</p>}
        {whs.isError && <p className="text-danger text-sm">Lỗi: {apiError(whs.error)}</p>}
        <div className="space-y-3">
          {branchRows.map((b, i) => (
            <div key={b.code} className="flex items-center gap-3">
              <span className="w-28 text-sm shrink-0">{b.name}</span>
              <div className="flex-1 h-2.5 bg-ink-3 rounded-full overflow-hidden">
                <div className="h-full rounded-full bg-flame" style={{ width: `${(b.value / maxBranch) * 100}%` }} />
              </div>
              <span className="w-24 text-right text-sm tabular-nums">
                {perWh[i]?.isLoading ? '…' : compactVnd(b.value)}
              </span>
            </div>
          ))}
          {!whs.isLoading && branchRows.length === 0 && <p className="text-txt-2 text-sm">Chưa có kho.</p>}
        </div>
      </Card>

      <Card>
        <SectionTitle>⚠️ Hàng cần chú ý (sắp hết)</SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Sản phẩm</Th><Th>Vị trí</Th><Th className="text-right">Tồn</Th><Th className="text-right">Tối thiểu</Th><Th>Tình trạng</Th>
          </tr></thead>
          <tbody>
            {low.isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
            {low.isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(low.error)}</RowMsg>}
            {low.data && low.data.results.length === 0 && <RowMsg colSpan={5}>Không có hàng sắp hết. 🎉</RowMsg>}
            {low.data?.results.map((i) => (
              <tr key={i.id} className="border-b border-line/50 last:border-0">
                <Td className="font-medium">{i.item_name}</Td>
                <Td className="font-mono text-txt-2">{i.bin_code}</Td>
                <Td className="text-right text-danger tabular-nums">{i.qty_on_hand}</Td>
                <Td className="text-right text-txt-2 tabular-nums">{i.min_level}</Td>
                <Td><Tag tone="danger">Sắp hết</Tag></Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </div>
  )
}
