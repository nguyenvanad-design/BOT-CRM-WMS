/**
 * Tokinarc frontend — src/pages/crm/ContractDetailModal.tsx
 * Xem chi tiết hợp đồng (read-only) trước khi duyệt/ký.
 */
import type { ReactNode } from 'react'
import { ScrollText } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { Tag, Button } from '@/components/ui'
import { formatVnd, formatDate, CONTRACT_STATUS_LABEL, CONTRACT_STATUS_TONE } from '@/lib/crm'
import type { Contract } from '@/lib/types'

export function ContractDetailModal({ contract, open, onClose, footer }: {
  contract: Contract | null; open: boolean; onClose: () => void; footer?: ReactNode
}) {
  const c = contract
  const debt = c ? Number(c.value_vnd || 0) - Number(c.paid_vnd || 0) : 0
  return (
    <Modal open={open} onClose={onClose} wide
      title={c ? `Hợp đồng ${c.code}` : 'Hợp đồng'}
      icon={<ScrollText size={18} className="text-flame" />}
      footer={footer ?? <Button variant="ghost" onClick={onClose}>Đóng</Button>}>
      {c && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Info label="Khách hàng" value={c.customer_name} />
            <Info label="Người lập" value={c.owner_username} />
            <Info label="Tiêu đề" value={c.title || '—'} />
            <Info label="Trạng thái"
              value={<Tag tone={CONTRACT_STATUS_TONE[c.status]}>{CONTRACT_STATUS_LABEL[c.status]}</Tag>} />
            <Info label="Hiệu lực"
              value={c.start_date ? `${formatDate(c.start_date)} – ${formatDate(c.end_date)}` : 'chưa ký'} />
            <Info label="Chiết khấu" value={`${Number(c.discount_pct || 0)}%`} />
            <Info label="Giá trị HĐ" value={<span className="text-flame font-bold">{formatVnd(c.value_vnd)}</span>} />
            <Info label="Đã thanh toán" value={formatVnd(c.paid_vnd)} />
            <Info label="Còn lại" value={<span className={debt > 0 ? 'text-warn' : 'text-ok'}>{formatVnd(debt)}</span>} />
          </div>
          {c.notes && (
            <div>
              <div className="text-xs text-txt-2 mb-1">Ghi chú</div>
              <p className="text-sm bg-ink-3 rounded-md px-3 py-2 whitespace-pre-wrap">{c.notes}</p>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}

function Info({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-txt-2">{label}</div>
      <div className="mt-0.5 text-sm font-medium">{value}</div>
    </div>
  )
}
