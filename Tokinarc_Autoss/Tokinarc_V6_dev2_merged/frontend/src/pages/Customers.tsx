/**
 * Tokinarc frontend — src/pages/Customers.tsx
 * Gọi GET /crm/customers/ THẬT (React Query). Có search, phân trang, loading/empty/error.
 * Ownership filter là ở backend: sale chỉ thấy KH của mình, manager+ thấy hết.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Search, Users, Plus, Upload } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import {
  SEGMENT_LABEL, CUSTOMER_STATUS_LABEL, CUSTOMER_STATUS_TONE, formatDate,
} from '@/lib/crm'
import { TAG_CLASS } from '@/lib/crm'
import type { Customer, Paginated } from '@/lib/types'
import { Button } from '@/components/ui'
import { useAuth, isManager } from '@/lib/auth/store'
import { CustomerForm } from '@/pages/crm/forms/CustomerForm'
import { ImportModal } from '@/pages/crm/ImportModal'

async function fetchCustomers(search: string, page: number) {
  const res = await api.get<Paginated<Customer>>('/crm/customers/', {
    params: { search: search || undefined, page },
  })
  return res.data
}

export function CustomersPage() {
  const nav = useNavigate()
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const canImport = isManager(useAuth((s) => s.user?.role))

  // debounce search 350ms
  useDebounce(search, 350, (v) => { setDebounced(v); setPage(1) })

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['customers', debounced, page],
    queryFn: () => fetchCustomers(debounced, page),
    placeholderData: keepPreviousData,
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.count / 20)) : 1

  return (
    <div className="max-w-7xl">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-5">
        <div>
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <Users size={20} className="text-flame" /> Khách hàng
          </h1>
          {data && <p className="text-xs text-txt-2 mt-0.5">{data.count} khách hàng</p>}
        </div>
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative flex-1 sm:flex-none">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-txt-2" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tìm tên, mã KH…"
              className="bg-ink-2 border border-line rounded-md pl-9 pr-3 py-2 text-sm w-full sm:w-64
                         focus:border-flame transition-colors"
            />
          </div>
          {canImport && (
            <Button variant="ghost" onClick={() => setImportOpen(true)}>
              <Upload size={14} /> Import
            </Button>
          )}
          <Button onClick={() => setFormOpen(true)}><Plus size={14} /> Thêm KH</Button>
        </div>
      </div>

      <div className="border border-line rounded-lg overflow-x-auto bg-ink-2">
        <table className="w-full min-w-[980px] text-sm">
          <thead>
            <tr className="text-left text-xs text-txt-2 border-b border-line">
              <th className="px-4 py-2.5 font-medium">Tên</th>
              <th className="px-4 py-2.5 font-medium">SĐT</th>
              <th className="px-4 py-2.5 font-medium">Email</th>
              <th className="px-4 py-2.5 font-medium">Nguồn</th>
              <th className="px-4 py-2.5 font-medium">Phân khúc</th>
              <th className="px-4 py-2.5 font-medium">Vùng</th>
              <th className="px-4 py-2.5 font-medium">Sale phụ trách</th>
              <th className="px-4 py-2.5 font-medium">Ngày tạo</th>
              <th className="px-4 py-2.5 font-medium">Nội dung</th>
              <th className="px-4 py-2.5 font-medium">Trạng thái</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && <RowMsg colSpan={10}>Đang tải…</RowMsg>}
            {isError && <RowMsg colSpan={10} danger>Lỗi: {apiError(error)}</RowMsg>}
            {data?.results.length === 0 && (
              <RowMsg colSpan={10}>Không có khách hàng nào khớp.</RowMsg>
            )}
            {data?.results.map((c) => (
              <tr key={c.id} onClick={() => nav(`/customers/${c.id}`)}
                className="border-b border-line/50 last:border-0 hover:bg-ink-3/40 cursor-pointer">
                <td className="px-4 py-2.5 font-medium whitespace-nowrap">{c.name}</td>
                <td className="px-4 py-2.5 text-txt-2 whitespace-nowrap">{c.primary_phone || '—'}</td>
                <td className="px-4 py-2.5 text-txt-2">{c.primary_email || '—'}</td>
                <td className="px-4 py-2.5 text-txt-2">{c.source || '—'}</td>
                <td className="px-4 py-2.5 text-txt-2">{SEGMENT_LABEL[c.segment] ?? (c.segment || '—')}</td>
                <td className="px-4 py-2.5 text-txt-2">{c.region || '—'}</td>
                <td className="px-4 py-2.5 text-txt-2 whitespace-nowrap">{c.owner_username || '—'}</td>
                <td className="px-4 py-2.5 text-txt-2 whitespace-nowrap">{formatDate(c.created_at)}</td>
                <td className="px-4 py-2.5 text-txt-2 max-w-[220px]">
                  <div className="truncate" title={c.notes}>{c.notes || '—'}</div>
                </td>
                <td className="px-4 py-2.5">
                  <span className={`text-xs border rounded-full px-2 py-0.5 ${TAG_CLASS[CUSTOMER_STATUS_TONE[c.status] ?? 'gray']}`}>
                    {CUSTOMER_STATUS_LABEL[c.status] ?? c.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {data && data.count > 20 && (
        <div className="flex items-center justify-between mt-3 text-sm">
          <span className="text-txt-2 text-xs">
            Trang {page}/{totalPages} {isFetching && '· đang tải…'}
          </span>
          <div className="flex gap-2">
            <PgBtn disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Trước</PgBtn>
            <PgBtn disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Sau</PgBtn>
          </div>
        </div>
      )}

      <CustomerForm open={formOpen} onClose={() => setFormOpen(false)} />
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} spec={{
        title: 'Import khách hàng cũ',
        importUrl: '/crm/customers/import/',
        templateUrl: '/crm/customers/import-template/',
        templateFilename: 'mau_import_khach_hang.xlsx',
        invalidateKey: 'customers',
        hint: 'Mỗi dòng = 1 KH (+ 1 người liên hệ chính tùy chọn).',
      }} />
    </div>
  )
}

function RowMsg({ children, colSpan, danger }: {
  children: React.ReactNode; colSpan: number; danger?: boolean
}) {
  return (
    <tr>
      <td colSpan={colSpan} className={`px-4 py-10 text-center text-sm ${danger ? 'text-danger' : 'text-txt-2'}`}>
        {children}
      </td>
    </tr>
  )
}

function PgBtn({ children, disabled, onClick }: {
  children: React.ReactNode; disabled?: boolean; onClick: () => void
}) {
  return (
    <button
      disabled={disabled} onClick={onClick}
      className="border border-line rounded-md px-3 py-1.5 text-xs disabled:opacity-40
                 disabled:cursor-not-allowed hover:bg-ink-3 transition-colors"
    >
      {children}
    </button>
  )
}

// debounce helper nhỏ gọn
import { useEffect, useRef } from 'react'
function useDebounce(value: string, ms: number, cb: (v: string) => void) {
  const cbRef = useRef(cb); cbRef.current = cb
  useEffect(() => {
    const t = setTimeout(() => cbRef.current(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
}
