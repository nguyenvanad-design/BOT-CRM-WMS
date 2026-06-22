/**
 * Tokinarc frontend — src/pages/wms/CycleCount.tsx
 * Phiên kiểm kê kho: tạo phiên → quét đếm (mã + ô + số đếm) → xem chênh lệch →
 * Áp dụng (điều chỉnh tồn). POST /wms/cycle-counts/ + /{id}/scan/ + /{id}/apply/.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, Plus, ScanLine, CheckCheck } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { useAuth, isWmsControl } from '@/lib/auth/store'
import { PageHeader, Card, Button, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'

interface CCLine { id: string; bin_code: string; part_name: string; system_qty: number; counted_qty: number; diff: number }
interface CC { id: string; code: string; warehouse_code: string; status: string; lines: CCLine[] }

export function WmsCycleCountPage() {
  const qc = useQueryClient()
  const canApply = isWmsControl(useAuth((s) => s.user?.role))
  const [openId, setOpenId] = useState<string | null>(null)
  const [code, setCode] = useState(''); const [bin, setBin] = useState(''); const [counted, setCounted] = useState('')

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
      <PageHeader icon={<ClipboardCheck size={20} className="text-flame" />} title="Kiểm kê kho"
        subtitle="Tạo phiên → quét đếm → áp dụng điều chỉnh tồn"
        actions={<Button onClick={() => create.mutate()} disabled={create.isPending || !warehouses.data?.length}>
          <Plus size={14} /> Phiên mới</Button>} />

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
              <div className="grid grid-cols-3 gap-2">
                <Inp label="Mã hàng" v={code} set={setCode} ph="Quét/nhập mã" />
                <Inp label="Mã ô" v={bin} set={setBin} ph="HCM-A-R01-B01" />
                <div className="flex gap-2 items-end">
                  <Inp label="Số đếm" v={counted} set={setCounted} ph="0" type="number" />
                  <Button onClick={() => scan.mutate()} disabled={scan.isPending}><ScanLine size={14} /></Button>
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
