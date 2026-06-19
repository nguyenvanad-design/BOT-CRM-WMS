/**
 * Tokinarc frontend — src/pages/crm/Opportunities.tsx
 * Danh sách cơ hội THẬT (GET /crm/opportunities/). Phân trang.
 * (Backend chưa bật search/filter cho opportunity nên không có ô tìm kiếm.)
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Target, Plus } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { compactVnd, formatDate, OPP_STAGE_LABEL, OPP_STAGE_TONE } from '@/lib/crm'
import type { Opportunity } from '@/lib/types'
import {
  PageHeader, Button, Tag, Gauge, TableCard, Th, Td, RowMsg, Pagination,
} from '@/components/ui'
import { OpportunityForm } from '@/pages/crm/forms/OpportunityForm'

export function OpportunitiesPage() {
  const nav = useNavigate()
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const openCreate = () => setFormOpen(true)

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['opportunities', page],
    queryFn: () => fetchPage<Opportunity>('/crm/opportunities/', { page }),
    placeholderData: keepPreviousData,
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

  return (
    <div className="max-w-6xl">
      <PageHeader
        icon={<Target size={20} className="text-flame" />}
        title="Opportunity"
        subtitle={data ? `${data.count} cơ hội` : undefined}
        actions={<Button onClick={openCreate}><Plus size={14} /> Tạo Opportunity</Button>}
      />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Tên cơ hội</Th><Th>Khách hàng</Th><Th className="text-right">Giá trị</Th>
            <Th className="w-40">Xác suất</Th><Th>Dự kiến chốt</Th><Th>Giai đoạn</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={6}>Chưa có cơ hội nào.</RowMsg>}
          {data?.results.map((o) => (
            <tr key={o.id} onClick={() => nav(`/opportunities/${o.id}`)}
              className="border-b border-line/50 last:border-0 hover:bg-ink-3/40 cursor-pointer">
              <Td className="font-medium">{o.title}</Td>
              <Td className="text-txt-2">{o.customer_name}</Td>
              <Td className="text-right text-flame tabular-nums">{compactVnd(o.est_value_vnd)}</Td>
              <Td><Gauge pct={o.probability} tone={o.probability >= 70 ? 'ok' : 'warn'} /></Td>
              <Td className="text-txt-2">{formatDate(o.expected_close)}</Td>
              <Td><Tag tone={OPP_STAGE_TONE[o.stage]}>{OPP_STAGE_LABEL[o.stage]}</Tag></Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      {data && data.count > PAGE_SIZE && (
        <Pagination
          page={page} totalPages={totalPages} fetching={isFetching}
          onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)}
        />
      )}

      <OpportunityForm open={formOpen} onClose={() => setFormOpen(false)} editing={editing} />
    </div>
  )
}
