/**
 * Tokinarc frontend — src/pages/wms/WarehouseMap.tsx
 * Bản đồ kho: lưới bin nhóm theo kho → zone, tô màu bin có tồn (xanh) / trống.
 * Dữ liệu từ /wms/bins/ + /wms/inventory/.
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Map as MapIcon, Search, X } from 'lucide-react'
import { fetchAll } from '@/lib/list'
import { apiError } from '@/lib/api'
import type { InventoryItem } from '@/lib/types'
import { Card, PageHeader } from '@/components/ui'

interface Bin { id: string; warehouse_code: string; zone_code: string; zone_name: string; rack: string; bin_code: string; full_code: string }

// Dịch loại sản phẩm (category) sang tên kệ tiếng Việt — để tìm hàng dễ.
const CATEGORY_VI: Record<string, string> = {
  TorchBody: 'Thân súng', Handle: 'Tay cầm', CableAssembly: 'Bộ dây cáp',
  PowerCable: 'Cáp nguồn', InnerTube: 'Ống dẫn trong',
  Tip: 'Béc hàn', TipBody: 'Thân béc', TipAdapter: 'Đầu nối béc',
  Nozzle: 'Chụp khí', CeramicNozzle: 'Chụp sứ', LavaNozzle: 'Chụp Lava',
  Orifice: 'Lỗ phun', Collet: 'Collet (kẹp)', ColletBody: 'Thân collet',
  GasLensColletBody: 'Thân collet gas lens', GasLensInsulator: 'Cách điện gas lens',
  Liner: 'Ruột gà (liner)', liner: 'Ruột gà (liner)', GuideTube: 'Ống dẫn hướng',
  LinerORing: 'Gioăng ruột gà', GasHose: 'Dây khí',
  InsulationCollar: 'Vòng cách điện', InsulationSpacer: 'Đệm cách điện',
  Insulator: 'Cách điện', BackCap: 'Nắp sau', ORing: 'Gioăng O', Gasket: 'Gioăng',
  WaveWasher: 'Long đền sóng', TungstenElectrode: 'Điện cực Tungsten', Tool: 'Dụng cụ',
  RobotBracket: 'Giá robot', RobotFlange: 'Mặt bích robot', AlignmentFixture: 'Đồ gá căn chỉnh',
  WXCenterCeramic: 'Sứ tâm WX', WXNozzleSpacer: 'Đệm chụp WX', WXNozzleAdapter: 'Đầu nối chụp WX',
  WXNozzleNut: 'Đai ốc chụp WX', WXNozzleSleeve: 'Ống chụp WX', WXCoverRubber: 'Cao su che WX',
}
const catVi = (c?: string) => (c ? CATEGORY_VI[c] ?? c : '')

export function WarehouseMapPage() {
  // page_size lớn để lấy đủ mọi ô/tồn trong 1 lượt (kho có thể >900 vị trí).
  const bins = useQuery({ queryKey: ['wms-map-bins'], queryFn: () => fetchAll<Bin>('/wms/bins/', { page_size: 2000 }) })
  const inv = useQuery({ queryKey: ['wms-map-inv'], queryFn: () => fetchAll<InventoryItem>('/wms/inventory/', { page_size: 2000 }) })

  // bin id → mã hàng thật + tên + loại + tồn (mỗi ô đúng 1 mã).
  const binInfo = new Map<string, { code: string; name: string; category: string; qty: number }>()
  for (const i of inv.data?.items ?? []) {
    binInfo.set(String(i.bin), {
      code: i.part || i.torch || '?', name: i.item_name, category: i.category ?? '', qty: i.qty_on_hand,
    })
  }
  const list = bins.data?.items ?? []

  // Tên kệ = loại hàng trong kệ; nhãn tầng = dải mã trên tầng.
  const keLabel = (tangs: Record<string, Bin[]>) => {
    for (const arr of Object.values(tangs)) for (const b of arr) {
      const c = binInfo.get(String(b.id))?.category
      if (c) return catVi(c)
    }
    return ''
  }
  const tangLabel = (arr: Bin[]) => {
    const codes = arr.map((b) => binInfo.get(String(b.id))?.code).filter(Boolean).sort() as string[]
    if (!codes.length) return ''
    return codes.length === 1 ? codes[0] : `${codes[0]}…${codes[codes.length - 1]}`
  }

  // Nhóm: warehouse → zone → kệ → tầng → bins[]  (rack dạng "K01-T2"; ô = bin_code)
  type Tang = Record<string, Bin[]>
  type Ke = Record<string, Tang>
  const grouped: Record<string, Record<string, Ke>> = {}
  const zoneNames: Record<string, string> = {}
  for (const b of list) {
    const [ke, tang = '-'] = b.rack.split('-T')
    zoneNames[b.zone_code] = b.zone_name
    const z = ((grouped[b.warehouse_code] ??= {})[b.zone_code] ??= {})
    ;((z[ke] ??= {})[tang] ??= []).push(b)
  }
  // Tầng cao xếp trên cùng (giống kệ thật): T4, T3, T2, T1.
  const tangKeys = (ke: Tang) => Object.keys(ke).sort((a, b) => b.localeCompare(a))

  // ── Tìm kiếm: gõ mã/tên → tô sáng ô khớp + cuộn tới ô đầu tiên ──
  const [q, setQ] = useState('')
  const query = q.trim().toLowerCase()
  const matched = new Set<string>()
  let firstMatchId = ''
  if (query) {
    for (const b of list) {
      const info = binInfo.get(String(b.id))
      const hay = `${info?.code ?? ''} ${info?.name ?? ''} ${b.full_code}`.toLowerCase()
      if (hay.includes(query)) { matched.add(b.id); if (!firstMatchId) firstMatchId = b.id }
    }
  }
  const firstMatchRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (firstMatchId) firstMatchRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [firstMatchId])

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<MapIcon size={20} className="text-flame" />} title="Bản đồ kho"
        subtitle={bins.data ? `${bins.data.count} vị trí` : undefined} />

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-txt-2" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm mã hàng / tên… (vd 018035)"
            className="w-72 bg-ink-3 border border-line rounded-md pl-8 pr-8 py-2 text-sm focus:border-flame focus:outline-none" />
          {q && (
            <button onClick={() => setQ('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-txt-2 hover:text-txt">
              <X size={14} />
            </button>
          )}
        </div>
        {query && (
          <span className={`text-xs ${matched.size ? 'text-flame' : 'text-danger'}`}>
            {matched.size ? `${matched.size} ô khớp — đã cuộn tới ô đầu` : 'Không tìm thấy ô nào'}
          </span>
        )}
        <div className="flex items-center gap-4 text-xs text-txt-2 ml-auto">
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-flame inline-block" /> Có hàng</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-ink-3 border border-line inline-block" /> Trống</span>
        </div>
      </div>

      {bins.isLoading && <p className="text-txt-2 text-sm">Đang tải…</p>}
      {bins.isError && <p className="text-danger text-sm">Lỗi: {apiError(bins.error)}</p>}

      <div className="space-y-4">
        {Object.entries(grouped).map(([wh, zones]) => (
          <Card key={wh}>
            <div className="text-sm font-semibold mb-3">Kho <span className="font-mono text-flame">{wh}</span></div>
            <div className="space-y-4">
              {Object.entries(zones).map(([zone, kes]) => (
                <div key={zone}>
                  <div className="text-xs font-semibold text-txt mb-2">
                    <span className="text-flame">Zone {zone}</span>
                    {zoneNames[zone] && <span className="text-txt-2 font-normal"> — {zoneNames[zone]}</span>}
                  </div>
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(kes).map(([ke, tangs]) => (
                      <div key={ke} className="border border-line rounded-lg p-2 bg-ink-2/40">
                        <div className="mb-1.5 text-center leading-tight">
                          <div className="text-[10px] font-mono text-txt-2">Kệ {ke}</div>
                          {keLabel(tangs) && <div className="text-[10px] text-flame/90 font-medium">{keLabel(tangs)}</div>}
                        </div>
                        <div className="space-y-1.5">
                          {tangKeys(tangs).map((t) => (
                            <div key={t}>
                              {t !== '-' && (
                                <div className="text-[9px] text-txt-2 mb-0.5">
                                  Tầng {t} <span className="font-mono text-txt-3">· {tangLabel(tangs[t])}</span>
                                </div>
                              )}
                              <div className="flex gap-1">
                                {tangs[t].map((b) => {
                                  const info = binInfo.get(String(b.id))
                                  const has = (info?.qty ?? 0) > 0
                                  const isMatch = matched.has(b.id)
                                  return (
                                    <div key={b.id}
                                      ref={b.id === firstMatchId ? firstMatchRef : undefined}
                                      title={`${b.full_code} — ${info?.name ?? 'trống'}${info ? ` (tồn ${info.qty})` : ''}`}
                                      className={`min-w-[3.5rem] h-6 px-1 grid place-items-center rounded text-[9px] font-mono border truncate transition-opacity ${
                                        has ? 'bg-flame/25 border-flame/50 text-flame' : 'bg-ink-3 border-line text-txt-2'
                                      } ${isMatch ? 'ring-2 ring-yellow-400 ring-offset-1 ring-offset-ink-2 !text-yellow-300 !border-yellow-400' : ''} ${
                                        query && !isMatch ? 'opacity-25' : ''
                                      }`}>
                                      {info?.code ?? b.bin_code}
                                    </div>
                                  )
                                })}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
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
