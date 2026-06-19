/**
 * Tokinarc frontend — src/pages/crm/Quotes.tsx
 * Danh sách báo giá THẬT (GET /crm/quotes/) + hành động:
 *   - Duyệt   → POST /crm/quotes/{id}/approve/      (chỉ manager/admin)
 *   - Tạo HĐ  → POST /crm/quotes/{id}/to-contract/  (khi đã duyệt)
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { FileText, Check, ArrowRight, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { compactVnd, formatDate, QUOTE_STATUS_LABEL, QUOTE_STATUS_TONE } from '@/lib/crm'
import { useAuth, isManager } from '@/lib/auth/store'
import type { Quote } from '@/lib/types'
import {
  PageHeader, Tag, Button, TableCard, Th, Td, RowMsg, Pagination,
} from '@/components/ui'
import { QuoteForm } from '@/pages/crm/forms/QuoteForm'

export function QuotesPage() {
  const qc = useQueryClient()
  const role = useAuth((s) => s.user?.role)
  const canApprove = isManager(role)
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Quote | null>(null)
  const openCreate = () => { setEditing(null); setFormOpen(true) }
  // Chỉ cho sửa khi còn nháp (draft) — đã gửi/duyệt thì khóa.
  const openEdit = (q: Quote) => { if (q.status === 'draft') { setEditing(q); setFormOpen(true) } }

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['quotes', page],
    queryFn: () => fetchPage<Quote>('/crm/quotes/', { page }),
    placeholderData: keepPreviousData,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['quotes'] })
    qc.invalidateQueries({ queryKey: ['dash'] })
  }

  const approve = useMutation({
    mutationFn: (id: string) => api.post(`/crm/quotes/${id}/approve/`),
    onSuccess: () => { toast.success('Đã duyệt báo giá'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const toContract = useMutation({
    mutationFn: (id: string) => api.post(`/crm/quotes/${id}/to-contract/`),
    onSuccess: (res) => { toast.success(`Đã tạo HĐ ${res.data.contract_order_code ?? ''}`); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

  return (
    <div className="max-w-6xl">
      <PageHeader
        icon={<FileText size={20} className="text-flame" />}
        title="Báo giá"
        subtitle={data ? `${data.count} báo giá` : undefined}
        actions={<Button onClick={openCreate}><Plus size={14} /> Tạo BG</Button>}
      />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Mã BG</Th><Th>Khách hàng</Th><Th className="text-right">Giá trị</Th>
            <Th>Hạn</Th><Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={6}>Chưa có báo giá nào.</RowMsg>}
          {data?.results.map((q) => (
            <tr key={q.id} onClick={() => openEdit(q)}
              className={`border-b border-line/50 last:border-0 hover:bg-ink-3/40 ${q.status === 'draft' ? 'cursor-pointer' : ''}`}>
              <Td className="font-mono text-flame">{q.code}</Td>
              <Td className="font-medium">{q.customer_name}</Td>
              <Td className="text-right tabular-nums">{compactVnd(q.total_vnd)}</Td>
              <Td className="text-txt-2">{formatDate(q.due_date)}</Td>
              <Td><Tag tone={QUOTE_STATUS_TONE[q.status]}>{QUOTE_STATUS_LABEL[q.status]}</Tag></Td>
              <Td className="text-right" onClick={(e) => e.stopPropagation()}>
                {(q.status === 'draft' || q.status === 'sent') && canApprove && (
                  <Button
                    variant="success" size="sm"
                    disabled={approve.isPending && approve.variables === q.id}
                    onClick={() => approve.mutate(q.id)}
                  >
                    <Check size={13} /> Duyệt
                  </Button>
                )}
                {q.status === 'approved' && (
                  <Button
                    size="sm"
                    disabled={toContract.isPending && toContract.variables === q.id}
                    onClick={() => toContract.mutate(q.id)}
                  >
                    Tạo HĐ <ArrowRight size={13} />
                  </Button>
                )}
                {q.status === 'converted' && (
                  <span className="text-[11px] text-txt-2 font-mono">{q.contract_order_code || 'Đã chuyển'}</span>
                )}
                {(q.status === 'draft' || q.status === 'sent') && !canApprove && (
                  <span className="text-[11px] text-txt-2">Chờ duyệt</span>
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

      <QuoteForm open={formOpen} onClose={() => setFormOpen(false)} editing={editing} />
    </div>
  )
}
