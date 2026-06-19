/**
 * Tokinarc frontend — src/pages/crm/OpportunityDetail.tsx
 * Chi tiết 1 Cơ hội + TIMELINE tư vấn (hoạt động + visit GẮN với cơ hội này).
 * GET /crm/opportunities/{id}/ + /crm/activities/?opportunity= + /crm/visits/?opportunity=
 */
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Target, Pencil, Phone, MapPin } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import {
  compactVnd, formatDate, OPP_STAGE_LABEL, OPP_STAGE_TONE,
  ACTIVITY_TYPE_LABEL, ACTIVITY_TYPE_TONE,
} from '@/lib/crm'
import type { Opportunity, Activity, Visit } from '@/lib/types'
import { Card, SectionTitle, StatCard, Tag, Gauge } from '@/components/ui'
import { OpportunityForm } from '@/pages/crm/forms/OpportunityForm'

interface TimelineItem { date: string; kind: 'activity' | 'visit'; label: string; detail: string; who: string; tone: string }

export function OpportunityDetailPage() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const [editOpen, setEditOpen] = useState(false)

  const opp = useQuery({
    queryKey: ['opportunity', id],
    queryFn: async () => (await api.get<Opportunity>(`/crm/opportunities/${id}/`)).data,
    enabled: !!id,
  })
  const acts = useQuery({
    queryKey: ['opp-acts', id],
    queryFn: async () => (await api.get<{ results: Activity[] }>('/crm/activities/', { params: { opportunity: id } })).data.results,
    enabled: !!id,
  })
  const visits = useQuery({
    queryKey: ['opp-visits', id],
    queryFn: async () => (await api.get<{ results: Visit[] }>('/crm/visits/', { params: { opportunity: id } })).data.results,
    enabled: !!id,
  })

  if (opp.isLoading) return <div className="max-w-4xl"><p className="text-txt-2 text-sm">Đang tải…</p></div>
  if (opp.isError) return <div className="max-w-4xl"><p className="text-danger text-sm">Lỗi: {apiError(opp.error)}</p></div>

  const o = opp.data!
  const timeline: TimelineItem[] = [
    ...(acts.data ?? []).map((a) => ({
      date: a.activity_date, kind: 'activity' as const,
      label: a.activity_type_display, detail: a.content, who: a.owner_username,
      tone: ACTIVITY_TYPE_TONE[a.activity_type] ?? 'gray',
    })),
    ...(visits.data ?? []).map((v) => ({
      date: v.visit_date, kind: 'visit' as const,
      label: 'Visit: ' + v.purpose, detail: v.summary || v.next_action, who: v.owner_username, tone: 'flame',
    })),
  ].sort((a, b) => (b.date || '').localeCompare(a.date || ''))

  return (
    <div className="max-w-4xl">
      <button onClick={() => nav(-1)} className="flex items-center gap-1.5 text-xs text-txt-2 hover:text-txt mb-3">
        <ArrowLeft size={14} /> Quay lại
      </button>

      <div className="flex items-center gap-3 mb-5">
        <div className="w-11 h-11 rounded-lg bg-flame/15 grid place-items-center">
          <Target size={22} className="text-flame" />
        </div>
        <div className="flex-1">
          <h1 className="text-lg font-semibold flex items-center gap-2">
            {o.title}
            <Tag tone={OPP_STAGE_TONE[o.stage]}>{OPP_STAGE_LABEL[o.stage]}</Tag>
          </h1>
          <p className="text-xs text-txt-2 mt-0.5">{o.customer_name}</p>
        </div>
        <button onClick={() => setEditOpen(true)}
          className="flex items-center gap-1.5 text-sm text-txt-2 hover:text-txt border border-line rounded-md px-3 py-1.5 transition-colors">
          <Pencil size={14} /> Sửa
        </button>
      </div>

      <OpportunityForm open={editOpen} onClose={() => setEditOpen(false)} editing={o} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Giá trị ước tính" tone="flame" value={compactVnd(o.est_value_vnd)} />
        <StatCard label="Xác suất" tone="txt" value={`${o.probability}%`} />
        <StatCard label="Dự kiến chốt" tone="blue" value={<span className="text-sm">{formatDate(o.expected_close)}</span>} />
        <StatCard label="Lượt tư vấn" tone="ok" value={(acts.data?.length ?? 0) + (visits.data?.length ?? 0)} />
      </div>

      {o.notes && (
        <Card className="mb-4">
          <SectionTitle>Yêu cầu / Ghi chú</SectionTitle>
          <p className="text-sm text-txt-2 whitespace-pre-wrap">{o.notes}</p>
        </Card>
      )}

      <Card>
        <SectionTitle>Timeline tư vấn ({timeline.length})</SectionTitle>
        {(acts.isLoading || visits.isLoading) && <p className="text-txt-2 text-sm">Đang tải…</p>}
        {timeline.length === 0 && !acts.isLoading && (
          <p className="text-txt-2 text-sm py-4 text-center">
            Chưa có hoạt động/visit nào gắn cơ hội này. Ghi ở menu Hoạt động/Visit và chọn cơ hội này.
          </p>
        )}
        <div className="space-y-3">
          {timeline.map((t, i) => (
            <div key={i} className="flex gap-3">
              <div className="mt-1.5 w-2 h-2 rounded-full bg-flame shrink-0" />
              <div className="flex-1 border-b border-line/50 pb-3">
                <div className="flex items-center gap-2 text-sm">
                  {t.kind === 'visit' ? <MapPin size={13} className="text-flame" /> : <Phone size={13} className="text-txt-2" />}
                  <Tag tone={t.tone as never}>{t.label}</Tag>
                  <span className="text-xs text-txt-2 ml-auto">{formatDate(t.date)} · {t.who}</span>
                </div>
                {t.detail && <p className="text-sm text-txt-2 mt-1.5">{t.detail}</p>}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
