/**
 * Tokinarc frontend — src/pages/crm/Products.tsx
 * Tra cứu sản phẩm THẬT từ catalog (838 phụ tùng + 122 súng hàn).
 * 2 tab: Phụ tùng / Súng hàn — search + phân trang.
 */
import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Wrench, Flame } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { useDebounced } from '@/lib/useDebounced'
import type { CatalogPart, CatalogTorch } from '@/lib/types'
import {
  PageHeader, SearchInput, Tag, TableCard, Th, Td, RowMsg, Pagination,
} from '@/components/ui'

type TabKey = 'parts' | 'torches'

export function ProductsPage() {
  const [tab, setTab] = useState<TabKey>('parts')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const debounced = useDebounced(search, 350, () => setPage(1))

  const switchTab = (t: TabKey) => { setTab(t); setSearch(''); setPage(1) }

  return (
    <div className="max-w-6xl">
      <PageHeader
        icon={<Wrench size={20} className="text-flame" />}
        title="Sản phẩm"
        actions={<SearchInput value={search} onChange={setSearch} placeholder="Tìm mã, tên sản phẩm…" />}
      />

      <div className="flex gap-1 mb-4 border-b border-line">
        <TabBtn active={tab === 'parts'} onClick={() => switchTab('parts')} icon={<Wrench size={14} />}>Phụ tùng</TabBtn>
        <TabBtn active={tab === 'torches'} onClick={() => switchTab('torches')} icon={<Flame size={14} />}>Súng hàn</TabBtn>
      </div>

      {tab === 'parts'
        ? <PartsTable search={debounced} page={page} setPage={setPage} />
        : <TorchesTable search={debounced} page={page} setPage={setPage} />}
    </div>
  )
}

function TabBtn({ active, onClick, icon, children }: {
  active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode
}) {
  return (
    <button onClick={onClick}
      className={`flex items-center gap-1.5 px-4 py-2 text-sm -mb-px border-b-2 transition-colors ${
        active ? 'border-flame text-flame font-semibold' : 'border-transparent text-txt-2 hover:text-txt'
      }`}>
      {icon}{children}
    </button>
  )
}

function PriceCell({ display, contact }: { display: string; contact: boolean }) {
  if (contact) return <Tag tone="purple">Liên hệ</Tag>
  return <span className="tabular-nums">{display || '—'}</span>
}

function PartsTable({ search, page, setPage }: { search: string; page: number; setPage: (f: (p: number) => number) => void }) {
  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['catalog-parts', search, page],
    queryFn: () => fetchPage<CatalogPart>('/catalog/parts/', { search: search || undefined, page }),
    placeholderData: keepPreviousData,
  })
  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1
  return (
    <>
      {data && <p className="text-xs text-txt-2 mb-2">{data.count} phụ tùng</p>}
      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Mã</Th><Th>Tên</Th><Th>Nhóm</Th><Th>Hệ</Th><Th className="text-right">Giá</Th>
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={5}>Không tìm thấy phụ tùng.</RowMsg>}
          {data?.results.map((p) => (
            <tr key={p.tokin_part_no} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="font-mono text-flame">{p.tokin_part_no}{p.is_priority_sell && <Tag tone="warn"> ưu tiên</Tag>}</Td>
              <Td className="font-medium">{p.display_name_vi || p.display_name_en || '—'}</Td>
              <Td className="text-txt-2">{p.category || '—'}</Td>
              <Td className="text-txt-2">{p.ecosystem || '—'}</Td>
              <Td className="text-right"><PriceCell display={p.price_display} contact={p.is_contact_price} /></Td>
            </tr>
          ))}
        </tbody>
      </TableCard>
      {data && data.count > PAGE_SIZE && (
        <Pagination page={page} totalPages={totalPages} fetching={isFetching}
          onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)} />
      )}
    </>
  )
}

function TorchesTable({ search, page, setPage }: { search: string; page: number; setPage: (f: (p: number) => number) => void }) {
  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['catalog-torches', search, page],
    queryFn: () => fetchPage<CatalogTorch>('/catalog/torches/', { search: search || undefined, page }),
    placeholderData: keepPreviousData,
  })
  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1
  return (
    <>
      {data && <p className="text-xs text-txt-2 mb-2">{data.count} súng hàn</p>}
      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Model</Th><Th>Tên</Th><Th>Dòng</Th><Th>Làm mát</Th><Th className="text-right">Dòng (A)</Th><Th className="text-right">Giá</Th>
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={6}>Không tìm thấy súng hàn.</RowMsg>}
          {data?.results.map((t) => (
            <tr key={t.model_code} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="font-mono text-flame">{t.model_code}</Td>
              <Td className="font-medium">{t.display_name_vi || t.display_name_en || '—'}</Td>
              <Td className="text-txt-2">{t.family || '—'}</Td>
              <Td className="text-txt-2">{t.cooling === 'water' ? 'Nước' : t.cooling === 'air' ? 'Khí' : (t.cooling || '—')}</Td>
              <Td className="text-right tabular-nums text-txt-2">{t.rated_dc_a ?? '—'}</Td>
              <Td className="text-right"><PriceCell display={t.price_display} contact={t.is_contact_price} /></Td>
            </tr>
          ))}
        </tbody>
      </TableCard>
      {data && data.count > PAGE_SIZE && (
        <Pagination page={page} totalPages={totalPages} fetching={isFetching}
          onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)} />
      )}
    </>
  )
}
