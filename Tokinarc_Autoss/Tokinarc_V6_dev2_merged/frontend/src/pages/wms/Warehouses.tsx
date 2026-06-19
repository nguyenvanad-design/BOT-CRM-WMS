/**
 * Tokinarc frontend — src/pages/wms/Warehouses.tsx
 * Kho & vị trí THẬT: GET /wms/warehouses/ + đếm bin theo kho (/wms/bins/?warehouse=).
 */
import { useQuery } from '@tanstack/react-query'
import { Warehouse as WarehouseIcon, Star } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import type { Warehouse } from '@/lib/types'
import { Card, PageHeader, Tag } from '@/components/ui'

interface Bin { id: string; warehouse_code: string; full_code: string }

export function WarehousesPage() {
  const wh = useQuery({
    queryKey: ['wms-warehouses'],
    queryFn: () => fetchAll<Warehouse>('/wms/warehouses/'),
  })
  const bins = useQuery({
    queryKey: ['wms-bins-all'],
    queryFn: () => fetchAll<Bin>('/wms/bins/'),
  })

  const binCount = (code: string) =>
    (bins.data?.items ?? []).filter((b) => b.warehouse_code === code).length

  return (
    <div className="max-w-4xl">
      <PageHeader icon={<WarehouseIcon size={20} className="text-flame" />} title="Kho & vị trí"
        subtitle={wh.data ? `${wh.data.count} kho` : undefined} />

      {wh.isLoading && <p className="text-txt-2 text-sm">Đang tải…</p>}
      {wh.isError && <p className="text-danger text-sm">Lỗi: {apiError(wh.error)}</p>}

      <div className="grid sm:grid-cols-2 gap-3">
        {wh.data?.items.map((w) => (
          <Card key={w.id}>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-flame font-semibold">{w.code}</span>
              {w.is_default && <Tag tone="ok"><Star size={10} className="inline -mt-0.5" /> Mặc định</Tag>}
              {!w.is_active && <Tag tone="gray">Ngừng</Tag>}
            </div>
            <div className="text-sm font-medium">{w.name}</div>
            <div className="text-xs text-txt-2 mt-2">
              {bins.isLoading ? 'Đang đếm vị trí…' : `${binCount(w.code)} vị trí (bin)`}
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
