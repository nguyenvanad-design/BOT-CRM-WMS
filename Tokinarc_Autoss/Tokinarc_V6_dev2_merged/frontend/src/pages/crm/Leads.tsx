/**
 * Tokinarc frontend — src/pages/crm/Leads.tsx
 * Danh sách Lead THẬT (GET /crm/leads/) + hành động convert → Customer
 * (POST /crm/leads/{id}/convert/). Search + phân trang.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { Radar, ArrowRight, Plus, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { LEAD_STATUS_LABEL, LEAD_STATUS_TONE, leadScoreTone, formatDate } from '@/lib/crm'
import type { Lead } from '@/lib/types'
import {
  PageHeader, SearchInput, Tag, Button, TableCard, Th, Td, RowMsg, Pagination,
} from '@/components/ui'
import { useDebounced } from '@/lib/useDebounced'
import { useAuth, isManager } from '@/lib/auth/store'
import { LeadForm } from '@/pages/crm/forms/LeadForm'
import { OpportunityForm } from '@/pages/crm/forms/OpportunityForm'
import { ImportModal } from '@/pages/crm/ImportModal'

export function LeadsPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const canImport = isManager(useAuth((s) => s.user?.role))
  const [editing, setEditing] = useState<Lead | null>(null)
  const [oppOpen, setOppOpen] = useState(false)
  const [oppPreset, setOppPreset] = useState<{ customer: string; title: string; notes: string } | undefined>()
  const debounced = useDebounced(search, 350, () => setPage(1))

  const openCreate = () => { setEditing(null); setFormOpen(true) }
  const openEdit = (l: Lead) => { setEditing(l); setFormOpen(true) }

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['leads', debounced, page],
    queryFn: () => fetchPage<Lead>('/crm/leads/', { search: debounced || undefined, page }),
    placeholderData: keepPreviousData,
  })

  const convert = useMutation({
    mutationFn: (v: { id: string; lead?: Lead; withOpp?: boolean }) => api.post(`/crm/leads/${v.id}/convert/`),
    onSuccess: async (res, v) => {
      toast.success(`Đã chuyển thành KH ${res.data.customer_code ?? ''}`)
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['customers'] })
      qc.invalidateQueries({ queryKey: ['dash'] })
      if (v.withOpp && v.lead) {
        // Chờ KH mới vào dropdown TRƯỚC khi mở form, để ô Khách hàng hiện đúng (không bị "Chọn KH").
        await qc.refetchQueries({ queryKey: ['customer-options'] })
        setOppPreset({
          customer: res.data.customer_id,
          title: `Cơ hội - ${v.lead.company || v.lead.name}`,
          notes: v.lead.notes || '',
        })
        setOppOpen(true)   // mở form Cơ hội điền sẵn khách + ghi chú lead
      }
    },
    onError: (e) => toast.error(apiError(e)),
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

  return (
    <div className="max-w-7xl">
      <PageHeader
        icon={<Radar size={20} className="text-flame" />}
        title="Leads"
        subtitle={data ? `${data.count} lead` : undefined}
        actions={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Tìm tên, công ty…" />
            {canImport && (
              <Button variant="ghost" onClick={() => setImportOpen(true)}><Upload size={14} /> Import</Button>
            )}
            <Button onClick={openCreate}><Plus size={14} /> Tạo Lead</Button>
          </>
        }
      />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Tên / Công ty</Th><Th>SĐT</Th><Th>Email</Th><Th>Nguồn</Th>
            <Th>Sale phụ trách</Th><Th>Ngày tạo</Th><Th>Nội dung</Th>
            <Th>Trạng thái</Th><Th className="text-right">Thao tác</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={9}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={9} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={9}>Không có lead nào.</RowMsg>}
          {data?.results.map((l) => (
            <tr key={l.id} onClick={() => openEdit(l)}
              className="border-b border-line/50 last:border-0 hover:bg-ink-3/40 cursor-pointer">
              <Td>
                <div className="font-medium flex items-center gap-1.5">
                  {l.name}
                  <Tag tone={leadScoreTone(l.score)}>{l.score}</Tag>
                </div>
                {l.company && <div className="text-[11px] text-txt-2">{l.company}</div>}
              </Td>
              <Td className="text-txt-2 whitespace-nowrap">{l.phone || '—'}</Td>
              <Td className="text-txt-2">{l.email || '—'}</Td>
              <Td className="text-txt-2">{l.source_display || l.source || '—'}</Td>
              <Td className="text-txt-2 whitespace-nowrap">{l.owner_username || '—'}</Td>
              <Td className="text-txt-2 whitespace-nowrap">{formatDate(l.created_at)}</Td>
              <Td className="text-txt-2 max-w-[240px]">
                <div className="truncate" title={l.notes}>{l.notes || '—'}</div>
              </Td>
              <Td><Tag tone={LEAD_STATUS_TONE[l.status]}>{LEAD_STATUS_LABEL[l.status]}</Tag></Td>
              <Td className="text-right" onClick={(e) => e.stopPropagation()}>
                {l.converted_customer ? (
                  <span className="text-[11px] text-txt-2">Đã chuyển</span>
                ) : (
                  <div className="flex gap-1.5 justify-end">
                    <Button
                      size="sm" variant="ghost"
                      disabled={convert.isPending && convert.variables?.id === l.id}
                      onClick={() => convert.mutate({ id: l.id })}
                    >
                      Chuyển KH
                    </Button>
                    <Button
                      size="sm"
                      disabled={convert.isPending && convert.variables?.id === l.id}
                      onClick={() => convert.mutate({ id: l.id, lead: l, withOpp: true })}
                    >
                      + Cơ hội <ArrowRight size={13} />
                    </Button>
                  </div>
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
      <OpportunityForm open={oppOpen} onClose={() => setOppOpen(false)} preset={oppPreset} />
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} spec={{
        title: 'Import Lead cũ',
        importUrl: '/crm/import/leads/',
        templateUrl: '/crm/import/leads/template/',
        templateFilename: 'mau_import_leads.xlsx',
        invalidateKey: 'leads',
        hint: 'Mỗi dòng = 1 lead. Trùng theo tên + SĐT sẽ bỏ qua.',
      }} />
    </div>
  )
}
