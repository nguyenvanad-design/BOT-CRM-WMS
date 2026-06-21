/**
 * Tokinarc frontend — src/pages/crm/Receivables.tsx
 * Trang Công nợ phải thu: GET /crm/receivables/ (lọc theo quyền — sale thấy KH
 * mình, manager+ thấy hết). Hiển thị tổng quan + tuổi nợ + danh sách thu hồi.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Wallet, Upload } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { compactVnd, formatVnd } from '@/lib/crm'
import type { ReceivablesResponse, DebtBucket } from '@/lib/types'
import {
  PageHeader, StatCard, Button, Tag, TableCard, Th, Td, RowMsg,
} from '@/components/ui'
import type { TagTone } from '@/lib/crm'
import { useAuth, isManager } from '@/lib/auth/store'
import { ImportModal } from '@/pages/crm/ImportModal'

const BUCKET_LABEL: Record<DebtBucket, string> = {
  current: 'Trong hạn', d1_30: 'Quá 1-30 ngày', d31_60: 'Quá 31-60 ngày', d60p: 'Quá >60 ngày',
}
const BUCKET_TONE: Record<DebtBucket, TagTone> = {
  current: 'ok', d1_30: 'warn', d31_60: 'flame', d60p: 'danger',
}

export function ReceivablesPage() {
  const nav = useNavigate()
  const [importOpen, setImportOpen] = useState(false)
  const canImport = isManager(useAuth((st) => st.user?.role))
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['receivables'],
    queryFn: async () => (await api.get<ReceivablesResponse>('/crm/receivables/')).data,
  })

  const s = data?.summary

  return (
    <div className="max-w-6xl">
      <PageHeader
        icon={<Wallet size={20} className="text-flame" />}
        title="Công nợ"
        subtitle={s ? `${s.count} đơn còn nợ` : undefined}
        actions={canImport && (
          <Button variant="ghost" onClick={() => setImportOpen(true)}><Upload size={14} /> Import đơn cũ</Button>
        )}
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Tổng phải thu" tone="flame" value={isLoading ? '…' : compactVnd(s?.total_due)} />
        <StatCard label="Trong hạn" tone="ok" value={isLoading ? '…' : compactVnd(s?.current)} />
        <StatCard label="Quá hạn" tone="danger" value={isLoading ? '…' : compactVnd(s?.overdue)} />
        <StatCard label="Quá >60 ngày" tone="danger" value={isLoading ? '…' : compactVnd(s?.d60p)} />
      </div>

      {/* Phân tích tuổi nợ */}
      {s && s.total_due > 0 && (
        <div className="bg-ink-2 border border-line rounded-lg p-4 mb-4">
          <div className="text-sm font-semibold mb-3">Phân tích tuổi nợ</div>
          <div className="space-y-2">
            {(['current', 'd1_30', 'd31_60', 'd60p'] as DebtBucket[]).map((b) => {
              const val = s[b]
              const pct = s.total_due ? Math.round((val / s.total_due) * 100) : 0
              const barTone: Record<DebtBucket, string> = {
                current: 'bg-ok', d1_30: 'bg-warn', d31_60: 'bg-flame', d60p: 'bg-danger',
              }
              return (
                <div key={b} className="flex items-center gap-3">
                  <span className="w-32 text-xs text-txt-2 shrink-0">{BUCKET_LABEL[b]}</span>
                  <div className="flex-1 h-2.5 bg-ink-3 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${barTone[b]}`} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="w-24 text-right text-xs tabular-nums">{compactVnd(val)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Mã đơn</Th><Th>Khách hàng</Th><Th className="text-right">Số nợ</Th>
            <Th className="text-right">Quá hạn</Th><Th>Nhóm</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data && data.results.length === 0 && <RowMsg colSpan={5}>Không có công nợ phải thu. 🎉</RowMsg>}
          {data?.results.map((r) => (
            <tr key={r.code} onClick={() => nav(`/customers/${r.customer_id}`)}
              className="border-b border-line/50 last:border-0 hover:bg-ink-3/40 cursor-pointer">
              <Td className="font-mono text-flame">{r.code}</Td>
              <Td className="font-medium">{r.customer}</Td>
              <Td className="text-right tabular-nums">{formatVnd(r.amount_due)}</Td>
              <Td className="text-right tabular-nums">
                {r.days_overdue > 0
                  ? <span className="text-danger">{r.days_overdue} ngày</span>
                  : <span className="text-txt-2">—</span>}
              </Td>
              <Td><Tag tone={BUCKET_TONE[r.bucket]}>{BUCKET_LABEL[r.bucket]}</Tag></Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} spec={{
        title: 'Import Đơn hàng cũ',
        importUrl: '/crm/import/orders/',
        templateUrl: '/crm/import/orders/template/',
        templateFilename: 'mau_import_don_hang.xlsx',
        invalidateKey: 'receivables',
        hint: 'Cột customer_code = mã KH; issued_date dạng 2024-03-20. Trùng mã đơn sẽ bỏ qua.',
      }} />
    </div>
  )
}
