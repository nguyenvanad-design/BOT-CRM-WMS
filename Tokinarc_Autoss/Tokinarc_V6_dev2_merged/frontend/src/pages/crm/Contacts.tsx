/**
 * Tokinarc frontend — src/pages/crm/Contacts.tsx
 * Người liên hệ THẬT (GET /crm/contacts/) + thêm/sửa. Search + phân trang.
 */
import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Contact as ContactIcon, Plus, Star } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { useDebounced } from '@/lib/useDebounced'
import type { CrmContact } from '@/lib/types'
import {
  PageHeader, SearchInput, Button, Tag, TableCard, Th, Td, RowMsg, Pagination,
} from '@/components/ui'
import { ContactForm } from '@/pages/crm/forms/ContactForm'

const CHANNEL: Record<string, string> = { zalo: 'Zalo', phone: 'Điện thoại', email: 'Email', other: 'Khác' }

export function ContactsPage() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<CrmContact | null>(null)
  const debounced = useDebounced(search, 350, () => setPage(1))

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['contacts', debounced, page],
    queryFn: () => fetchPage<CrmContact>('/crm/contacts/', { search: debounced || undefined, page }),
    placeholderData: keepPreviousData,
  })
  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<ContactIcon size={20} className="text-flame" />} title="Người liên hệ"
        subtitle={data ? `${data.count} liên hệ` : undefined}
        actions={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Tìm tên, SĐT, công ty…" />
            <Button onClick={() => { setEditing(null); setFormOpen(true) }}><Plus size={14} /> Thêm</Button>
          </>
        } />

      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Họ tên</Th><Th>Chức vụ</Th><Th>Công ty</Th><Th>Điện thoại</Th><Th>Kênh</Th>
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={5}>Chưa có liên hệ nào.</RowMsg>}
          {data?.results.map((c) => (
            <tr key={c.id} onClick={() => { setEditing(c); setFormOpen(true) }}
              className="border-b border-line/50 last:border-0 hover:bg-ink-3/40 cursor-pointer">
              <Td className="font-medium">
                {c.full_name}{c.is_primary && <Star size={12} className="inline ml-1 text-flame fill-flame -mt-0.5" />}
              </Td>
              <Td className="text-txt-2">{c.title || '—'}</Td>
              <Td className="text-txt-2">{c.customer_name}</Td>
              <Td className="text-txt-2">{c.phone || '—'}</Td>
              <Td><Tag tone="gray">{CHANNEL[c.preferred_channel] ?? c.preferred_channel}</Tag></Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      {data && data.count > PAGE_SIZE && (
        <Pagination page={page} totalPages={totalPages} fetching={isFetching}
          onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)} />
      )}

      <ContactForm open={formOpen} onClose={() => setFormOpen(false)} editing={editing} />
    </div>
  )
}
