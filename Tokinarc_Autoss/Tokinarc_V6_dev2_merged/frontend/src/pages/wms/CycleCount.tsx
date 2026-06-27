/**
 * Tokinarc frontend — src/pages/wms/CycleCount.tsx
 * Phiên kiểm kê kho: tạo phiên → quét đếm (mã + ô + số đếm) → xem chênh lệch →
 * Áp dụng (điều chỉnh tồn). POST /wms/cycle-counts/ + /{id}/scan/ + /{id}/apply/.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, Plus, ScanLine, CheckCheck, Search, Link2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { useAuth, isWmsControl } from '@/lib/auth/store'
import { CameraScanner } from '@/components/CameraScanner'
import type { CatalogPart, SerialNumber } from '@/lib/types'
import { PageHeader, Card, Button, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'

interface CCLine { id: string; bin_code: string; part_name: string; system_qty: number; counted_qty: number; diff: number }
interface CC { id: string; code: string; warehouse_code: string; status: string; lines: CCLine[] }

export function WmsCycleCountPage() {
  const qc = useQueryClient()
  const canApply = isWmsControl(useAuth((s) => s.user?.role))
  const [tab, setTab] = useState<'count' | 'lookup'>('count')   // Kiểm kê / Tra cứu
  const [openId, setOpenId] = useState<string | null>(null)
  const [code, setCode] = useState(''); const [bin, setBin] = useState(''); const [counted, setCounted] = useState('')
  const [lookupQ, setLookupQ] = useState('')
  const [assigning, setAssigning] = useState(false)   // quét-gán: mã lạ → gán cho 1 SP
  const [assignPick, setAssignPick] = useState('')

  // Tra cứu: quét/nhập mã → tìm phụ tùng (catalog, có cả barcode) + serial (WMS).
  const lookup = useQuery({
    queryKey: ['scan-lookup', lookupQ],
    queryFn: async () => {
      const [parts, serials] = await Promise.all([
        api.get<{ results: CatalogPart[] }>('/catalog/parts/', { params: { search: lookupQ.trim() } }),
        api.get<{ results: SerialNumber[] }>('/wms/serials/', { params: { search: lookupQ.trim() } }),
      ])
      return { parts: parts.data.results.slice(0, 6), serials: serials.data.results.slice(0, 6) }
    },
    enabled: tab === 'lookup' && lookupQ.trim().length >= 2,
  })

  // Quét-gán: tìm SP để gán mã lạ vào.
  const assignSearch = useQuery({
    queryKey: ['assign-search', assignPick],
    queryFn: async () => (await api.get<{ results: CatalogPart[] }>('/catalog/parts/', { params: { search: assignPick.trim() } })).data.results.slice(0, 6),
    enabled: assigning && assignPick.trim().length >= 2,
  })
  const assignMut = useMutation({
    mutationFn: (partNo: string) => api.post(`/catalog/parts/${encodeURIComponent(partNo)}/set-barcode/`, { barcode: lookupQ.trim() }),
    onSuccess: (r) => {
      toast.success(`Đã gán "${lookupQ.trim()}" → ${r.data.part_no}. Lần sau quét ra ngay.`)
      setAssigning(false); setAssignPick('')
      qc.invalidateQueries({ queryKey: ['scan-lookup'] })
    },
    onError: (e) => toast.error(apiError(e)),
  })

  const list = useQuery({
    queryKey: ['cycle-counts'],
    queryFn: async () => (await api.get<{ results: CC[] }>('/wms/cycle-counts/')).data.results ?? [],
  })
  const detail = useQuery({
    queryKey: ['cycle-count', openId],
    queryFn: async () => (await api.get<CC>(`/wms/cycle-counts/${openId}/`)).data,
    enabled: !!openId,
  })

  const warehouses = useQuery({
    queryKey: ['wh-list'],
    queryFn: async () => (await api.get<{ results: { id: string; code: string }[] }>('/wms/warehouses/')).data.results ?? [],
  })

  const create = useMutation({
    mutationFn: () => api.post('/wms/cycle-counts/', { warehouse: warehouses.data?.[0]?.id }),
    onSuccess: (r) => { toast.success(`Đã tạo phiên ${r.data.code}`); setOpenId(r.data.id); qc.invalidateQueries({ queryKey: ['cycle-counts'] }) },
    onError: (e) => toast.error(apiError(e)),
  })
  const scan = useMutation({
    mutationFn: () => api.post(`/wms/cycle-counts/${openId}/scan/`, { code: code.trim(), bin_code: bin.trim(), counted_qty: Number(counted) }),
    onSuccess: () => { setCode(''); setCounted(''); qc.invalidateQueries({ queryKey: ['cycle-count', openId] }) },
    onError: (e) => toast.error(apiError(e)),
  })
  const apply = useMutation({
    mutationFn: () => api.post(`/wms/cycle-counts/${openId}/apply/`),
    onSuccess: (r) => { toast.success(`Đã áp dụng (${r.data.applied} dòng, chênh ${r.data.total_diff})`); qc.invalidateQueries({ queryKey: ['cycle-count', openId] }); qc.invalidateQueries({ queryKey: ['cycle-counts'] }) },
    onError: (e) => toast.error(apiError(e)),
  })

  const cc = detail.data

  return (
    <div className="max-w-3xl">
      <PageHeader icon={<ClipboardCheck size={20} className="text-flame" />} title="Kiểm kê & Tra cứu"
        subtitle="Kiểm kê: phiên → quét đếm → áp dụng · Tra cứu: quét xem SP + tồn"
        actions={tab === 'count'
          ? <Button onClick={() => create.mutate()} disabled={create.isPending || !warehouses.data?.length}>
              <Plus size={14} /> Phiên mới</Button>
          : undefined} />

      <div className="flex gap-1.5 mb-4">
        <button onClick={() => setTab('count')}
          className={`flex items-center gap-1.5 text-sm rounded-md px-3 py-1.5 border transition-colors ${tab === 'count' ? 'border-flame text-flame bg-flame/10' : 'border-line text-txt-2 hover:text-txt'}`}>
          <ClipboardCheck size={14} /> Kiểm kê
        </button>
        <button onClick={() => setTab('lookup')}
          className={`flex items-center gap-1.5 text-sm rounded-md px-3 py-1.5 border transition-colors ${tab === 'lookup' ? 'border-flame text-flame bg-flame/10' : 'border-line text-txt-2 hover:text-txt'}`}>
          <Search size={14} /> Tra cứu
        </button>
      </div>

      {/* TRA CỨU — quét/nhập mã → xem SP + tồn + serial */}
      {tab === 'lookup' && (
        <div className="max-w-xl space-y-3">
          <CameraScanner onScan={(c) => setLookupQ(c)} />
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-txt-2" />
            <input value={lookupQ} onChange={(e) => setLookupQ(e.target.value)}
              placeholder="Quét hoặc nhập mã hàng / serial…"
              className="w-full bg-ink-3 border border-line rounded-md pl-9 pr-3 py-2 text-sm focus:border-flame focus:outline-none" />
          </div>
          {lookup.isLoading && <p className="text-xs text-txt-2">Đang tìm…</p>}
          {lookup.data && lookup.data.parts.length === 0 && lookup.data.serials.length === 0 && lookupQ.trim().length >= 2 && (
            <Card>
              <p className="text-sm text-txt-2 mb-2">
                Không tìm thấy "<span className="font-mono text-flame">{lookupQ.trim()}</span>". Tem này có thể <b>chưa gán</b>.
              </p>
              {!assigning ? (
                <Button size="sm" onClick={() => setAssigning(true)}>
                  <Link2 size={14} /> Gán mã này cho sản phẩm
                </Button>
              ) : (
                <div className="space-y-2">
                  <p className="text-[11px] text-txt-2">Tìm & chọn sản phẩm để gán mã <span className="font-mono">{lookupQ.trim()}</span>:</p>
                  <input value={assignPick} onChange={(e) => setAssignPick(e.target.value)} autoFocus
                    placeholder="Tên hoặc mã sản phẩm…"
                    className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm focus:border-flame focus:outline-none" />
                  {(assignSearch.data ?? []).map((p) => (
                    <button key={p.tokin_part_no} disabled={assignMut.isPending}
                      onClick={() => assignMut.mutate(p.tokin_part_no)}
                      className="w-full text-left flex items-center gap-2 border border-line rounded-md px-3 py-1.5 text-sm hover:border-flame transition-colors">
                      <span className="font-mono text-flame">{p.tokin_part_no}</span>
                      <span className="flex-1">{p.display_name_vi}</span>
                      <Link2 size={13} className="text-txt-2" />
                    </button>
                  ))}
                  <button onClick={() => { setAssigning(false); setAssignPick('') }} className="text-xs text-txt-2 hover:text-txt">Hủy</button>
                </div>
              )}
            </Card>
          )}
          {(lookup.data?.parts ?? []).map((p) => (
            <Card key={p.tokin_part_no}>
              <div className="flex items-center gap-2">
                <span className="font-mono text-flame">{p.tokin_part_no}</span>
                <span className="text-sm flex-1">{p.display_name_vi}</span>
                <span className="text-sm tabular-nums text-txt-2">{p.price_display}</span>
              </div>
            </Card>
          ))}
          {(lookup.data?.serials ?? []).map((s) => (
            <Card key={s.serial}>
              <div className="flex items-center gap-2 text-sm">
                <span className="font-mono text-flame">{s.serial}</span>
                <span className="flex-1">{s.torch}</span>
                <Tag tone="gray">{s.status}</Tag>
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab === 'count' && (<>
      {!openId && (
        <TableCard>
          <thead><tr className="border-b border-line"><Th>Mã phiên</Th><Th>Kho</Th><Th>Trạng thái</Th><Th /></tr></thead>
          <tbody>
            {list.isLoading && <RowMsg colSpan={4}>Đang tải…</RowMsg>}
            {list.data?.length === 0 && <RowMsg colSpan={4}>Chưa có phiên kiểm kê.</RowMsg>}
            {list.data?.map((s) => (
              <tr key={s.id} className="border-b border-line/50 hover:bg-ink-3/40 cursor-pointer" onClick={() => setOpenId(s.id)}>
                <Td className="font-mono text-flame">{s.code}</Td>
                <Td>{s.warehouse_code}</Td>
                <Td><Tag tone={s.status === 'applied' ? 'ok' : s.status === 'open' ? 'warn' : 'gray'}>{s.status}</Tag></Td>
                <Td className="text-right text-xs text-txt-2">Mở</Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      )}

      {openId && cc && (
        <>
          <button onClick={() => setOpenId(null)} className="text-xs text-txt-2 hover:text-txt mb-3">← Danh sách phiên</button>
          <Card className="mb-4">
            <div className="flex items-center justify-between mb-3">
              <div><span className="font-mono text-flame">{cc.code}</span> · kho {cc.warehouse_code} ·{' '}
                <Tag tone={cc.status === 'applied' ? 'ok' : 'warn'}>{cc.status}</Tag></div>
              {cc.status === 'open' && canApply && (
                <Button variant="success" onClick={() => apply.mutate()} disabled={apply.isPending || cc.lines.length === 0}>
                  <CheckCheck size={14} /> Áp dụng</Button>
              )}
              {cc.status === 'open' && !canApply && (
                <span className="text-[11px] text-txt-2">Chờ Quản lý kho duyệt</span>
              )}
            </div>
            {cc.status === 'open' && (
              <div className="space-y-2">
                <CameraScanner onScan={(c) => setCode(c)} />
                <div className="grid grid-cols-3 gap-2">
                  <Inp label="Mã hàng" v={code} set={setCode} ph="Quét/nhập mã" />
                  <Inp label="Mã ô" v={bin} set={setBin} ph="HCM-A-R01-B01" />
                  <div className="flex gap-2 items-end">
                    <Inp label="Số đếm" v={counted} set={setCounted} ph="0" type="number" />
                    <Button onClick={() => scan.mutate()} disabled={scan.isPending}><ScanLine size={14} /></Button>
                  </div>
                </div>
              </div>
            )}
          </Card>

          <TableCard>
            <thead><tr className="border-b border-line"><Th>Ô</Th><Th>Mặt hàng</Th>
              <Th className="text-right">Hệ thống</Th><Th className="text-right">Đếm</Th><Th className="text-right">Chênh</Th></tr></thead>
            <tbody>
              {cc.lines.length === 0 && <RowMsg colSpan={5}>Chưa đếm dòng nào.</RowMsg>}
              {cc.lines.map((l) => (
                <tr key={l.id} className="border-b border-line/50">
                  <Td className="font-mono text-xs">{l.bin_code}</Td>
                  <Td>{l.part_name}</Td>
                  <Td className="text-right tabular-nums">{l.system_qty}</Td>
                  <Td className="text-right tabular-nums">{l.counted_qty}</Td>
                  <Td className={`text-right tabular-nums ${l.diff === 0 ? 'text-txt-2' : l.diff > 0 ? 'text-ok' : 'text-danger'}`}>
                    {l.diff > 0 ? `+${l.diff}` : l.diff}</Td>
                </tr>
              ))}
            </tbody>
          </TableCard>
        </>
      )}
      </>)}
    </div>
  )
}

function Inp({ label, v, set, ph, type = 'text' }: { label: string; v: string; set: (s: string) => void; ph?: string; type?: string }) {
  return (
    <div className="flex-1">
      <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">{label}</label>
      <input value={v} onChange={(e) => set(e.target.value)} placeholder={ph} type={type}
        className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm focus:border-flame focus:outline-none" />
    </div>
  )
}
