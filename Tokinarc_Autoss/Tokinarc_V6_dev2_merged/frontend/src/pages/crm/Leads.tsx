/**
 * Tokinarc frontend — src/pages/crm/Leads.tsx
 * Danh sách Lead THẬT (GET /crm/leads/) + hành động convert → Customer
 * (POST /crm/leads/{id}/convert/). Search + phân trang.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { Radar, ArrowRight, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { LEAD_STATUS_LABEL, LEAD_STATUS_TONE, leadScoreTone } from '@/lib/crm'
import type { Lead } from '@/lib/types'
import {
  PageHeader, SearchInput, Tag, Button, TableCard, Th, Td, RowMsg, Pagination,
} from '@/components/ui'
import { useDebounced } from '@/lib/useDebounced'
import { LeadForm } from '@/pages/crm/forms/LeadForm'

export function LeadsPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Lead | null>(null)
  const debounced = useDebounced(search, 350, () => setPage(1))

  const openCreate = () => { setEditing(null); setFormOpen(true) }
  const openEdit = (l: Lead) => { setEditing(l); setFormOpen(true) }

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['leads', debounced, page],
    queryFn: () => fetchPage<Lead>('/crm/leads/', { search: debounced || undefined, page }),
    placeholderData: keepPreviousData,
  })

  const convert = useMutation({
    mutationFn: (id: string) => api.post(`/crm/leads/${id}/convert/`),
    onSuccess: (res) => {
      toast.success(`Đã chuyển thành KH ${res.data.customer_code ?? ''}`)
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['dash'] })
    },
    onError: (e) => toast.error(apiError(e)),
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

  return (
    <div className="max-w-5xl">
      <PageHeader
        icon={<Radar size={20} className="text-flame" />}
        title="Leads"
        subtitle={data ? `${data.count} lead` : undefined}
        actions={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Tìm tên, công ty…" />
            <Button onClick={openCreate}><Plus size={14} /> Tạo Lead</Button>
          </>
        }
      />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Tên / Công ty</Th><Th>Liên hệ</Th><Th>Nguồn</Th>
            <Th className="text-right">Điểm</Th><Th>Trạng thái</Th><Th />
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={6}>Không có lead nào.</RowMsg>}
          {data?.results.map((l) => (
            <tr key={l.id} onClick={() => openEdit(l)}
              className="border-b border-line/50 last:border-0 hover:bg-ink-3/40 cursor-pointer">
              <Td>
                <div className="font-medium">{l.name}</div>
                {l.company && <div className="text-[11px] text-txt-2">{l.company}</div>}
              </Td>
              <Td className="text-txt-2">{l.phone || l.email || '—'}</Td>
              <Td className="text-txt-2">{l.source || '—'}</Td>
              <Td className="text-right">
                <Tag tone={leadScoreTone(l.score)}>{l.score}</Tag>
              </Td>
              <Td><Tag tone={LEAD_STATUS_TONE[l.status]}>{LEAD_STATUS_LABEL[l.status]}</Tag></Td>
              <Td className="text-right" onClick={(e) => e.stopPropagation()}>
                {l.converted_customer ? (
                  <span className="text-[11px] text-txt-2">Đã chuyển</span>
                ) : (
                  <Button
                    size="sm"
                    disabled={convert.isPending && convert.variables === l.id}
                    onClick={() => convert.mutate(l.id)}
                  >
                    Chuyển KH <ArrowRight size={13} />
                  </Button>
                )}
              </Td>
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

      <LeadForm open={formOpen} onClose={() => setFormOpen(false)} editing={editing} />
    </div>
  )
}
