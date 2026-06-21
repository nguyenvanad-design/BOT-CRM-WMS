/**
 * Tokinarc frontend — src/pages/crm/Contracts.tsx
 * Hợp đồng THẬT (GET /crm/contracts/) + KPI + thêm/sửa.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ScrollText, Plus, Upload } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import { compactVnd, formatVnd, formatDate, CONTRACT_STATUS_LABEL, CONTRACT_STATUS_TONE } from '@/lib/crm'
import type { Contract } from '@/lib/types'
import {
  PageHeader, StatCard, Button, Tag, TableCard, Th, Td, RowMsg,
} from '@/components/ui'
import { useAuth, isManager } from '@/lib/auth/store'
import { ContractForm } from '@/pages/crm/forms/ContractForm'
import { ImportModal } from '@/pages/crm/ImportModal'

export function ContractsPage() {
  const [formOpen, setFormOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const canImport = isManager(useAuth((s) => s.user?.role))
  const [editing, setEditing] = useState<Contract | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['contracts'],
    queryFn: () => fetchAll<Contract>('/crm/contracts/'),
  })
  const items = data?.items ?? []
  const count = (s: string) => items.filter((c) => c.status === s).length
  const totalValue = items.reduce((s, c) => s + Number(c.value_vnd || 0), 0)

  return (
    <div className="max-w-6xl">
      <PageHeader icon={<ScrollText size={20} className="text-flame" />} title="Hợp đồng"
        subtitle={data ? `${data.count} hợp đồng` : undefined}
        actions={
          <>
            {canImport && (
              <Button variant="ghost" onClick={() => setImportOpen(true)}><Upload size={14} /> Import</Button>
            )}
            <Button onClick={() => { setEditing(null); setFormOpen(true) }}><Plus size={14} /> Tạo HĐ</Button>
          </>
        } />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Hiệu lực" tone="ok" value={isLoading ? '…' : count('active')} />
        <StatCard label="Chờ ký" tone="warn" value={isLoading ? '…' : count('pending_sign')} />
        <StatCard label="Hết hạn" tone="danger" value={isLoading ? '…' : count('expired')} />
        <StatCard label="Tổng giá trị" tone="flame" value={isLoading ? '…' : compactVnd(totalValue)} />
      </div>

      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Mã HĐ</Th><Th>Khách hàng</Th><Th className="text-right">Giá trị</Th>
          <Th>Hiệu lực</Th><Th className="text-right">Còn nợ</Th><Th>Trạng thái</Th>
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data && items.length === 0 && <RowMsg colSpan={6}>Chưa có hợp đồng nào.</RowMsg>}
          {items.map((c) => (
            <tr key={c.id} onClick={() => { setEditing(c); setFormOpen(true) }}
              className="border-b border-line/50 last:border-0 hover:bg-ink-3/40 cursor-pointer">
              <Td className="font-mono text-flame">{c.code}</Td>
              <Td className="font-medium">{c.customer_name}</Td>
              <Td className="text-right tabular-nums">{compactVnd(c.value_vnd)}</Td>
              <Td className="text-txt-2 text-xs">{c.start_date ? `${formatDate(c.start_date)} – ${formatDate(c.end_date)}` : 'chưa ký'}</Td>
              <Td className="text-right tabular-nums">{c.debt_vnd > 0 ? <span className="text-warn">{formatVnd(c.debt_vnd)}</span> : <span className="text-ok">Đã xong</span>}</Td>
              <Td><Tag tone={CONTRACT_STATUS_TONE[c.status]}>{CONTRACT_STATUS_LABEL[c.status]}</Tag></Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      <ContractForm open={formOpen} onClose={() => setFormOpen(false)} editing={editing} />
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} spec={{
        title: 'Import Hợp đồng cũ',
        importUrl: '/crm/import/contracts/',
        templateUrl: '/crm/import/contracts/template/',
        templateFilename: 'mau_import_hop_dong.xlsx',
        invalidateKey: 'contracts',
        hint: 'Cột customer_code = mã KH đã có. Trùng mã HĐ sẽ bỏ qua.',
      }} />
    </div>
  )
}
