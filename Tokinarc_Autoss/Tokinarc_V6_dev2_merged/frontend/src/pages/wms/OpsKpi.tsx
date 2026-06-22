/**
 * Tokinarc frontend — src/pages/wms/OpsKpi.tsx
 * KPI vận hành kho (Quản lý kho+): năng suất nhập/xuất, độ chính xác kiểm kê,
 * tồn theo zone, hiệu suất nhân sự. GET /wms/ops-kpi/?warehouse=&days=.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Gauge, PackagePlus, PackageMinus, ClipboardCheck, AlertTriangle } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { PageHeader, Card, StatCard, TableCard, Th, Td, RowMsg } from '@/components/ui'

interface Kpi {
  warehouse: string; days: number
  inbound: { ops: number; qty: number }; outbound: { ops: number; qty: number }
  adjust_ops: number; transfer_ops: number
  cycle_count: { sessions: number; lines: number; mismatch: number; abs_diff: number; accuracy_pct: number }
  by_user: { user: string; ops: number }[]
  by_zone: { zone: string; name: string; sku: number; qty: number }[]
  low_stock: number
}

export function WmsOpsKpiPage() {
  const [days, setDays] = useState(30)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['wms-ops-kpi', days],
    queryFn: async () => (await api.get<Kpi>('/wms/ops-kpi/', { params: { days } })).data,
  })

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<Gauge size={20} className="text-flame" />} title="KPI vận hành kho"
        subtitle="Năng suất, độ chính xác kiểm kê, tồn theo zone, hiệu suất nhân sự"
        actions={
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
            className="bg-ink-2 border border-line rounded-md px-3 py-2 text-sm">
            <option value={7}>7 ngày</option><option value={30}>30 ngày</option>
            <option value={90}>90 ngày</option>
          </select>
        } />

      {isLoading && <p className="text-txt-2 text-sm">Đang tải…</p>}
      {isError && <p className="text-danger text-sm">Lỗi: {apiError(error)} (cần quyền Quản lý kho)</p>}
      {data && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
            <StatCard label={`Nhập (${data.days}n)`} tone="ok"
              value={<span className="text-base">{data.inbound.qty} <span className="text-xs text-txt-2">/{data.inbound.ops} lần</span></span>} />
            <StatCard label={`Xuất (${data.days}n)`} tone="flame"
              value={<span className="text-base">{data.outbound.qty} <span className="text-xs text-txt-2">/{data.outbound.ops} lần</span></span>} />
            <StatCard label="Độ chính xác kiểm kê" tone={data.cycle_count.accuracy_pct >= 98 ? 'ok' : 'warn'}
              value={`${data.cycle_count.accuracy_pct}%`} />
            <StatCard label="Sắp hết hàng" tone="danger" value={data.low_stock} />
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            {/* Tồn theo zone */}
            <Card>
              <div className="text-sm font-semibold mb-2">Tồn theo zone</div>
              <TableCard>
                <thead><tr className="border-b border-line"><Th>Zone</Th><Th className="text-right">SKU</Th><Th className="text-right">Tồn</Th></tr></thead>
                <tbody>
                  {data.by_zone.length === 0 && <RowMsg colSpan={3}>Chưa có tồn.</RowMsg>}
                  {data.by_zone.map((z) => (
                    <tr key={z.zone} className="border-b border-line/50 last:border-0">
                      <Td><span className="font-mono text-flame">{z.zone}</span> <span className="text-txt-2 text-xs">{z.name}</span></Td>
                      <Td className="text-right tabular-nums">{z.sku}</Td>
                      <Td className="text-right tabular-nums">{z.qty}</Td>
                    </tr>
                  ))}
                </tbody>
              </TableCard>
            </Card>

            {/* Hiệu suất nhân sự */}
            <Card>
              <div className="text-sm font-semibold mb-2">Hiệu suất nhân sự (số thao tác)</div>
              <TableCard>
                <thead><tr className="border-b border-line"><Th>Nhân viên</Th><Th className="text-right">Thao tác</Th></tr></thead>
                <tbody>
                  {data.by_user.length === 0 && <RowMsg colSpan={2}>Chưa có thao tác.</RowMsg>}
                  {data.by_user.map((u) => (
                    <tr key={u.user} className="border-b border-line/50 last:border-0">
                      <Td>{u.user}</Td><Td className="text-right tabular-nums">{u.ops}</Td>
                    </tr>
                  ))}
                </tbody>
              </TableCard>
            </Card>
          </div>

          <Card className="mt-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
              <Mini icon={<PackagePlus size={14} className="text-green-400" />} label="Lần nhập" v={data.inbound.ops} />
              <Mini icon={<PackageMinus size={14} className="text-flame" />} label="Lần xuất" v={data.outbound.ops} />
              <Mini icon={<ClipboardCheck size={14} className="text-blue-400" />} label="Phiên kiểm kê" v={data.cycle_count.sessions} />
              <Mini icon={<AlertTriangle size={14} className="text-amber-400" />} label="Dòng lệch / chênh tuyệt đối" v={`${data.cycle_count.mismatch} / ${data.cycle_count.abs_diff}`} />
            </div>
          </Card>
        </>
      )}
    </div>
  )
}

function Mini({ icon, label, v }: { icon: React.ReactNode; label: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      {icon}
      <div><div className="text-[10px] uppercase tracking-wide text-txt-2">{label}</div>
        <div className="tabular-nums font-medium">{v}</div></div>
    </div>
  )
}
