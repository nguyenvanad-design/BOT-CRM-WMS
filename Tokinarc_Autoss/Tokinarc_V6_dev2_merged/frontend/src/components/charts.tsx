/**
 * Tokinarc frontend — src/components/charts.tsx
 * Biểu đồ cột tiền VND dùng chung (recharts), bám theme tối + lửa hàn.
 */
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { compactVnd } from '@/lib/crm'

interface Row { label: string; value: number }

const PALETTE = ['#e05c1b', '#58a6ff', '#3fb950', '#bc8cff', '#d29922', '#2dd4bf']

function MoneyTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-ink-3 border border-line rounded-md px-3 py-1.5 text-xs">
      <div className="text-txt-2">{payload[0].payload.label}</div>
      <div className="font-semibold text-flame">{compactVnd(payload[0].value)}</div>
    </div>
  )
}

export function MoneyBarChart({ data, height = 240, multicolor = false }: {
  data: Row[]; height?: number; multicolor?: boolean
}) {
  if (!data.length) {
    return <div className="text-txt-2 text-sm text-center py-10">Chưa có dữ liệu.</div>
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
        <XAxis dataKey="label" stroke="#8b949e" fontSize={11} tickLine={false} axisLine={{ stroke: '#30363d' }} />
        <YAxis stroke="#8b949e" fontSize={11} tickLine={false} axisLine={false}
          tickFormatter={(v) => compactVnd(v).replace('₫ ', '')} width={56} />
        <Tooltip content={<MoneyTooltip />} cursor={{ fill: 'rgba(224,92,27,0.08)' }} />
        <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={64}>
          {data.map((_, i) => (
            <Cell key={i} fill={multicolor ? PALETTE[i % PALETTE.length] : '#e05c1b'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
