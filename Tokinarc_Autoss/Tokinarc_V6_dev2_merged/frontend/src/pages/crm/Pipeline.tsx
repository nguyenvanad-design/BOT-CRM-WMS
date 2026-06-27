/**
 * Tokinarc frontend — src/pages/crm/Pipeline.tsx
 * Bảng kanban cơ hội theo giai đoạn. Kéo-thả deal sang cột khác →
 * POST /crm/opportunities/{id}/move-stage/ (cập nhật stage thật).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Filter } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import { compactVnd, OPP_STAGE_LABEL, OPP_STAGE_TONE, OPP_STAGE_ORDER } from '@/lib/crm'
import type { Opportunity, OppStage } from '@/lib/types'
import { PageHeader, Tag } from '@/components/ui'

export function PipelinePage({ embedded = false }: { embedded?: boolean }) {
  const qc = useQueryClient()
  const [dragId, setDragId] = useState<string | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['pipeline'],
    queryFn: () => fetchAll<Opportunity>('/crm/opportunities/'),
  })

  const move = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: OppStage }) =>
      api.post(`/crm/opportunities/${id}/move-stage/`, { stage }),
    onSuccess: (_res, vars) => {
      toast.success(`Đã chuyển sang "${OPP_STAGE_LABEL[vars.stage]}"`)
      qc.invalidateQueries({ queryKey: ['pipeline'] })
      qc.invalidateQueries({ queryKey: ['opportunities'] })
      qc.invalidateQueries({ queryKey: ['dash'] })
    },
    onError: (e) => toast.error(apiError(e)),
  })

  const items = data?.items ?? []

  const onDrop = (stage: OppStage) => {
    if (!dragId) return
    const opp = items.find((o) => o.id === dragId)
    setDragId(null)
    if (opp && opp.stage !== stage) move.mutate({ id: opp.id, stage })
  }

  if (isLoading) return <Shell embedded={embedded}><p className="text-txt-2 text-sm">Đang tải…</p></Shell>
  if (isError) return <Shell embedded={embedded}><p className="text-danger text-sm">Lỗi: {apiError(error)}</p></Shell>

  return (
    <Shell embedded={embedded}>
      <div className="flex gap-3 overflow-x-auto pb-2">
        {OPP_STAGE_ORDER.map((stage) => {
          const col = items.filter((o) => o.stage === stage)
          const sum = col.reduce((s, o) => s + Number(o.est_value_vnd || 0), 0)
          return (
            <div
              key={stage}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDrop(stage)}
              className="min-w-[220px] w-[220px] bg-ink-2 border border-line rounded-lg p-3 shrink-0"
            >
              <div className="flex items-center justify-between mb-2">
                <Tag tone={OPP_STAGE_TONE[stage]}>{OPP_STAGE_LABEL[stage]}</Tag>
                <span className="text-[11px] text-txt-2">{col.length}</span>
              </div>
              <div className="text-[11px] text-txt-2 mb-2 tabular-nums">{compactVnd(sum)}</div>
              <div className="space-y-2">
                {col.map((o) => (
                  <div
                    key={o.id}
                    draggable
                    onDragStart={() => setDragId(o.id)}
                    onDragEnd={() => setDragId(null)}
                    className="bg-ink-3 border border-transparent hover:border-flame rounded-md p-2.5
                               cursor-grab active:cursor-grabbing transition-colors"
                  >
                    <div className="text-xs font-semibold leading-tight">{o.title}</div>
                    <div className="text-[11px] text-flame mt-1 tabular-nums">{compactVnd(o.est_value_vnd)}</div>
                    <div className="text-[10px] text-txt-2 mt-1">{o.customer_name} · {o.probability}%</div>
                  </div>
                ))}
                {col.length === 0 && (
                  <div className="text-[11px] text-txt-2/60 text-center py-4 border border-dashed border-line rounded-md">
                    Kéo deal vào đây
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </Shell>
  )
}

function Shell({ children, embedded }: { children: React.ReactNode; embedded?: boolean }) {
  return (
    <div>
      {!embedded && (
        <PageHeader
          icon={<Filter size={20} className="text-flame" />}
          title="Pipeline"
          subtitle="Kéo-thả deal để đổi giai đoạn"
        />
      )}
      {children}
    </div>
  )
}
