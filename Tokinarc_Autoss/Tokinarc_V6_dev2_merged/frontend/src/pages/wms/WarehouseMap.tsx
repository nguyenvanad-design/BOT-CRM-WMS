/**
 * Tokinarc frontend — src/pages/wms/WarehouseMap.tsx
 * Bản đồ kho: lưới bin nhóm theo kho → zone, tô màu bin có tồn (xanh) / trống.
 * Dữ liệu từ /wms/bins/ + /wms/inventory/.
 */
import { useQuery } from '@tanstack/react-query'
import { Map as MapIcon } from 'lucide-react'
import { fetchAll } from '@/lib/list'
import { apiError } from '@/lib/api'
import type { InventoryItem } from '@/lib/types'
import { Card, PageHeader } from '@/components/ui'

interface Bin { id: string; warehouse_code: string; zone_code: string; rack: string; bin_code: string; full_code: string }

export function WarehouseMapPage() {
  const bins = useQuery({ queryKey: ['wms-map-bins'], queryFn: () => fetchAll<Bin>('/wms/bins/') })
  const inv = useQuery({ queryKey: ['wms-map-inv'], queryFn: () => fetchAll<InventoryItem>('/wms/inventory/') })

  const occupied = new Set((inv.data?.items ?? []).filter((i) => i.qty_on_hand > 0).map((i) => String(i.bin)))
  const list = bins.data?.items ?? []

  // Nhóm: warehouse_code → zone_code → bins[]
  const grouped: Record<string, Record<string, Bin[]>> = {}
  for (const b of list) {
    (grouped[b.warehouse_code] ??= {})[b.zone_code] ??= []
    grouped[b.warehouse_code][b.zone_code].push(b)
  }

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<MapIcon size={20} className="text-flame" />} title="Bản đồ kho"
        subtitle={bins.data ? `${bins.data.count} vị trí` : undefined} />

      <div className="flex items-center gap-4 mb-4 text-xs text-txt-2">
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-flame inline-block" /> Có hàng</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-ink-3 border border-line inline-block" /> Trống</span>
      </div>

      {bins.isLoading && <p className="text-txt-2 text-sm">Đang tải…</p>}
      {bins.isError && <p className="text-danger text-sm">Lỗi: {apiError(bins.error)}</p>}

      <div className="space-y-4">
        {Object.entries(grouped).map(([wh, zones]) => (
          <Card key={wh}>
            <div className="text-sm font-semibold mb-3">Kho <span className="font-mono text-flame">{wh}</span></div>
            <div className="space-y-3">
              {Object.entries(zones).map(([zone, zbins]) => (
                <div key={zone}>
                  <div className="text-xs text-txt-2 mb-1.5">Zone {zone}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {zbins.map((b) => {
                      const has = occupied.has(String(b.id))
                      return (
                        <div key={b.id} title={b.full_code}
                          className={`px-2 py-1.5 rounded text-[11px] font-mono border ${
                            has ? 'bg-flame/20 border-flame/40 text-flame' : 'bg-ink-3 border-line text-txt-2'
                          }`}>
                          {b.rack}-{b.bin_code}
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ))}
        {!bins.isLoading && list.length === 0 && <p className="text-txt-2 text-sm">Chưa có vị trí kho.</p>}
      </div>
    </div>
  )
}
