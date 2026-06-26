/**
 * Tokinarc frontend — src/pages/crm/Procedures.tsx
 * Tra cứu LẮP ĐẶT / SỬA CHỮA cho nhân sự nội bộ (kỹ sư, kho).
 * GET /catalog/procedures/?q=...&intent=INSTALLATION|REPAIR|LOOKUP
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Wrench, Search } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { PageHeader, Card, Tag, RowMsg } from '@/components/ui'

interface Proc { id: number; intent: string; intent_display: string; question: string; answer: string; source: string }

const FILTERS: { key: string; label: string }[] = [
  { key: '', label: 'Tất cả' },
  { key: 'INSTALLATION', label: 'Lắp đặt' },
  { key: 'REPAIR', label: 'Sửa chữa' },
  { key: 'LOOKUP', label: 'Tra cứu' },
]
const TONE: Record<string, 'blue' | 'warn' | 'gray'> = { INSTALLATION: 'blue', REPAIR: 'warn', LOOKUP: 'gray' }

export function ProceduresPage() {
  const [q, setQ] = useState('')
  const [intent, setIntent] = useState('')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['procedures', q, intent],
    queryFn: async () => (await api.get<{ count: number; results: Proc[] }>('/catalog/procedures/', {
      params: { q: q || undefined, intent: intent || undefined, page_size: 100 },
    })).data,
  })
  const rows = data?.results ?? []

  return (
    <div className="max-w-4xl">
      <PageHeader icon={<Wrench size={20} className="text-flame" />} title="Tra cứu Lắp đặt / Sửa chữa"
        subtitle={data ? `${data.count} hướng dẫn` : 'Quy trình lắp ráp, cách thay & xử lý lỗi súng hàn'} />

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-txt-2" />
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Tìm: liner, tip, nozzle, torque, thay béc…"
            className="w-full bg-ink-3 border border-line rounded-md pl-9 pr-3 py-2 text-sm focus:border-flame focus:outline-none" />
        </div>
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button key={f.key} onClick={() => setIntent(f.key)}
              className={`text-xs rounded-md px-2.5 py-2 border transition-colors ${
                intent === f.key ? 'border-flame text-flame bg-flame/10' : 'border-line text-txt-2 hover:text-txt'}`}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading && <p className="text-txt-2 text-sm">Đang tải…</p>}
      {isError && <p className="text-danger text-sm">Lỗi: {apiError(error)}</p>}
      {data && rows.length === 0 && (
        <Card><RowMsg colSpan={1}>Không có hướng dẫn khớp. Thử từ khóa tiếng Anh (liner, tip, nozzle, torque…).</RowMsg></Card>
      )}

      <div className="space-y-2.5">
        {rows.map((p) => (
          <Card key={p.id}>
            <div className="flex items-start gap-2 mb-1.5">
              <Tag tone={TONE[p.intent] ?? 'gray'}>{p.intent_display}</Tag>
              <div className="font-medium text-sm flex-1">{p.question}</div>
            </div>
            <pre className="text-sm text-txt-2 whitespace-pre-wrap font-sans leading-relaxed">{p.answer}</pre>
            {p.source && <div className="text-[11px] text-txt-3 mt-2">Nguồn: {p.source}</div>}
          </Card>
        ))}
      </div>
    </div>
  )
}
