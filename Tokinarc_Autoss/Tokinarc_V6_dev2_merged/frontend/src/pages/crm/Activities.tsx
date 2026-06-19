/**
 * Tokinarc frontend — src/pages/crm/Activities.tsx
 * Nhật ký hoạt động THẬT (GET /crm/activities/) + ghi mới.
 */
import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Phone, Plus } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { formatDate, ACTIVITY_TYPE_LABEL, ACTIVITY_TYPE_TONE } from '@/lib/crm'
import type { Activity } from '@/lib/types'
import {
  PageHeader, Button, Tag, TableCard, Th, Td, RowMsg, Pagination,
} from '@/components/ui'
import { ActivityForm } from '@/pages/crm/forms/ActivityForm'

export function ActivitiesPage() {
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['activities', page],
    queryFn: () => fetchPage<Activity>('/crm/activities/', { page }),
    placeholderData: keepPreviousData,
  })
  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<Phone size={20} className="text-flame" />} title="Hoạt động"
        subtitle={data ? `${data.count} hoạt động` : undefined}
        actions={<Button onClick={() => setFormOpen(true)}><Plus size={14} /> Ghi hoạt động</Button>} />

      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Thời gian</Th><Th>Khách hàng</Th><Th>Loại</Th><Th>Nội dung</Th><Th>Người</Th>
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={5}>Chưa có hoạt động nào.</RowMsg>}
          {data?.results.map((a) => (
            <tr key={a.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="text-txt-2 whitespace-nowrap">{formatDate(a.activity_date)}</Td>
              <Td className="font-medium">{a.customer_name}</Td>
              <Td><Tag tone={ACTIVITY_TYPE_TONE[a.activity_type]}>{ACTIVITY_TYPE_LABEL[a.activity_type]}</Tag></Td>
              <Td>{a.content || '—'}</Td>
              <Td className="text-txt-2">{a.owner_username}</Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      {data && data.count > PAGE_SIZE && (
        <Pagination page={page} totalPages={totalPages} fetching={isFetching}
          onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)} />
      )}

      <ActivityForm open={formOpen} onClose={() => setFormOpen(false)} />
    </div>
  )
}
