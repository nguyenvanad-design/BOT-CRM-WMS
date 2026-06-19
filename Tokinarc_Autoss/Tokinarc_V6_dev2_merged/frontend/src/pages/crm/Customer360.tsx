/**
 * Tokinarc frontend — src/pages/crm/Customer360.tsx
 * Customer 360: GET /crm/customers/{id}/360/ (KPI tổng hợp + thông tin + contacts)
 * và làm giàu bằng cơ hội/báo giá của KH (lọc client-side từ list endpoint).
 */
import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Building2, Phone, Mail, Star, Pencil } from 'lucide-react'
import { CustomerForm } from '@/pages/crm/forms/CustomerForm'
import { api, apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import {
  SEGMENT_LABEL, SEGMENT_TONE, CUSTOMER_STATUS_LABEL, CUSTOMER_STATUS_TONE,
  OPP_STAGE_LABEL, OPP_STAGE_TONE, QUOTE_STATUS_LABEL, QUOTE_STATUS_TONE,
  compactVnd, formatVnd, formatDate,
} from '@/lib/crm'
import type { Customer360, Opportunity, Quote } from '@/lib/types'
import {
  Card, SectionTitle, StatCard, Tag, TableCard, Th, Td, RowMsg,
} from '@/components/ui'

const CHANNEL_LABEL: Record<string, string> = {
  zalo: 'Zalo', phone: 'Điện thoại', email: 'Email', other: 'Khác',
}

export function Customer360Page() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const [editOpen, setEditOpen] = useState(false)

  const c360 = useQuery({
    queryKey: ['customer-360', id],
    queryFn: async () => (await api.get<Customer360>(`/crm/customers/${id}/360/`)).data,
    enabled: !!id,
  })
  const opps = useQuery({
    queryKey: ['customer-360', id, 'opps'],
    queryFn: () => fetchAll<Opportunity>('/crm/opportunities/'),
    enabled: !!id,
  })
  const quotes = useQuery({
    queryKey: ['customer-360', id, 'quotes'],
    queryFn: () => fetchAll<Quote>('/crm/quotes/'),
    enabled: !!id,
  })

  if (c360.isLoading) return <Wrap><p className="text-txt-2 text-sm">Đang tải…</p></Wrap>
  if (c360.isError) return <Wrap><p className="text-danger text-sm">Lỗi: {apiError(c360.error)}</p></Wrap>

  const d = c360.data!
  const cust = d.customer
  const myOpps = (opps.data?.items ?? []).filter((o) => o.customer === id)
  const myQuotes = (quotes.data?.items ?? []).filter((q) => q.customer === id)

  return (
    <Wrap>
      <button onClick={() => nav(-1)} className="flex items-center gap-1.5 text-xs text-txt-2 hover:text-txt mb-3">
        <ArrowLeft size={14} /> Quay lại
      </button>

      <div className="flex items-center gap-3 mb-5">
        <div className="w-11 h-11 rounded-lg bg-flame/15 grid place-items-center">
          <Building2 size={22} className="text-flame" />
        </div>
        <div className="flex-1">
          <h1 className="text-lg font-semibold flex items-center gap-2">
            {cust.name}
            <Tag tone={CUSTOMER_STATUS_TONE[cust.status] ?? 'gray'}>
              {CUSTOMER_STATUS_LABEL[cust.status] ?? cust.status}
            </Tag>
          </h1>
          <p className="text-xs text-txt-2 mt-0.5">
            <span className="font-mono text-flame">{cust.code}</span>
            {cust.region && ` · ${cust.region}`}
          </p>
        </div>
        <button onClick={() => setEditOpen(true)}
          className="flex items-center gap-1.5 text-sm text-txt-2 hover:text-txt border border-line rounded-md px-3 py-1.5 transition-colors">
          <Pencil size={14} /> Sửa
        </button>
      </div>

      <CustomerForm open={editOpen} onClose={() => setEditOpen(false)} editing={cust} />

      {/* KPI từ /360/ (backend hiện trả placeholder cho orders/debt) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Đơn đang mở" tone="blue" value={d.open_orders} />
        <StatCard label="Công nợ" tone="danger" value={compactVnd(d.debt_vnd)} />
        <StatCard label="Ticket mở" tone="warn" value={d.open_tickets} />
        <StatCard label="Hoạt động gần nhất" tone="txt"
          value={<span className="text-sm">{d.last_activity ? formatDate(d.last_activity) : '—'}</span>} />
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mb-4">
        {/* Thông tin */}
        <Card>
          <SectionTitle>Thông tin</SectionTitle>
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <Info label="Phân khúc">
              <Tag tone={SEGMENT_TONE[cust.segment] ?? 'gray'}>{SEGMENT_LABEL[cust.segment] ?? cust.segment}</Tag>
            </Info>
            <Info label="Mã số thuế">{cust.tax_code || '—'}</Info>
            <Info label="Phụ trách">{cust.owner_username || '—'}</Info>
            <Info label="Vùng">{cust.region || '—'}</Info>
            {cust.notes && <div className="col-span-2"><Info label="Ghi chú">{cust.notes}</Info></div>}
          </dl>
        </Card>

        {/* Liên hệ */}
        <Card>
          <SectionTitle>Người liên hệ ({cust.contacts.length})</SectionTitle>
          {cust.contacts.length === 0 ? (
            <p className="text-xs text-txt-2 py-4 text-center">Chưa có liên hệ.</p>
          ) : (
            <div className="space-y-2">
              {cust.contacts.map((ct) => (
                <div key={ct.id} className="flex items-center gap-3 border border-line rounded-lg p-2.5">
                  <div className="w-8 h-8 rounded-full bg-flame grid place-items-center text-white text-xs font-semibold shrink-0">
                    {ct.full_name.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium flex items-center gap-1.5">
                      {ct.full_name}
                      {ct.is_primary && <Star size={12} className="text-flame fill-flame" />}
                      {ct.title && <span className="text-[10px] text-txt-2 font-normal">· {ct.title}</span>}
                    </div>
                    <div className="text-[11px] text-txt-2 flex gap-3 mt-0.5">
                      {ct.phone && <span className="flex items-center gap-1"><Phone size={11} />{ct.phone}</span>}
                      {ct.email && <span className="flex items-center gap-1"><Mail size={11} />{ct.email}</span>}
                    </div>
                  </div>
                  <Tag tone="gray">{CHANNEL_LABEL[ct.preferred_channel] ?? ct.preferred_channel}</Tag>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Cơ hội của KH */}
      <Card className="mb-4">
        <SectionTitle action={<Link to="/opportunities" className="text-xs text-flame hover:underline">Tất cả cơ hội</Link>}>
          Cơ hội ({myOpps.length})
        </SectionTitle>
        <TableCard>
          <thead>
            <tr className="border-b border-line">
              <Th>Tên</Th><Th className="text-right">Giá trị</Th><Th>Xác suất</Th><Th>Dự kiến</Th><Th>Giai đoạn</Th>
            </tr>
          </thead>
          <tbody>
            {opps.isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
            {opps.data && myOpps.length === 0 && <RowMsg colSpan={5}>Chưa có cơ hội.</RowMsg>}
            {myOpps.map((o) => (
              <tr key={o.id} className="border-b border-line/50 last:border-0">
                <Td className="font-medium">{o.title}</Td>
                <Td className="text-right text-flame tabular-nums">{compactVnd(o.est_value_vnd)}</Td>
                <Td className="text-txt-2">{o.probability}%</Td>
                <Td className="text-txt-2">{formatDate(o.expected_close)}</Td>
                <Td><Tag tone={OPP_STAGE_TONE[o.stage]}>{OPP_STAGE_LABEL[o.stage]}</Tag></Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>

      {/* Báo giá của KH */}
      <Card>
        <SectionTitle action={<Link to="/quotes" className="text-xs text-flame hover:underline">Tất cả báo giá</Link>}>
          Báo giá ({myQuotes.length})
        </SectionTitle>
        <TableCard>
          <thead>
            <tr className="border-b border-line">
              <Th>Mã</Th><Th className="text-right">Giá trị</Th><Th>Hạn</Th><Th>Trạng thái</Th>
            </tr>
          </thead>
          <tbody>
            {quotes.isLoading && <RowMsg colSpan={4}>Đang tải…</RowMsg>}
            {quotes.data && myQuotes.length === 0 && <RowMsg colSpan={4}>Chưa có báo giá.</RowMsg>}
            {myQuotes.map((q) => (
              <tr key={q.id} className="border-b border-line/50 last:border-0">
                <Td className="font-mono text-flame">{q.code}</Td>
                <Td className="text-right tabular-nums">{formatVnd(q.total_vnd)}</Td>
                <Td className="text-txt-2">{formatDate(q.due_date)}</Td>
                <Td><Tag tone={QUOTE_STATUS_TONE[q.status]}>{QUOTE_STATUS_LABEL[q.status]}</Tag></Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </Wrap>
  )
}

function Wrap({ children }: { children: React.ReactNode }) {
  return <div className="max-w-5xl">{children}</div>
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-txt-2 font-semibold">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  )
}
