/**
 * Tokinarc frontend — src/pages/wms/OrderLinesModal.tsx
 * Modal "Xem nội dung" chung cho phiếu Nhập/Xuất kho: thông tin chung + bảng dòng
 * hàng (mặt hàng + 2 cột số lượng). Read-only.
 */
import type { ReactNode } from 'react'
import { PackageCheck } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'

export interface DocLine { key: string; name: string; code: string; q1: number; q2: number }

export function OrderLinesModal({ open, onClose, title, meta, q1Label, q2Label, lines }: {
  open: boolean; onClose: () => void; title: string; meta?: ReactNode
  q1Label: string; q2Label: string; lines: DocLine[]
}) {
  const totalQ1 = lines.reduce((s, l) => s + (l.q1 || 0), 0)
  const totalQ2 = lines.reduce((s, l) => s + (l.q2 || 0), 0)
  return (
    <Modal open={open} onClose={onClose} wide title={title}
      icon={<PackageCheck size={18} className="text-flame" />}
      footer={<Button variant="ghost" onClick={onClose}>Đóng</Button>}>
      {meta && <div className="mb-3">{meta}</div>}
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-txt-2 text-[11px] uppercase tracking-wide">
            <th className="text-left py-1.5">Mã</th>
            <th className="text-left">Mặt hàng</th>
            <th className="text-right">{q1Label}</th>
            <th className="text-right">{q2Label}</th>
            <th className="text-right">Lệch</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => {
            const diff = (l.q2 || 0) - (l.q1 || 0)
            const short = diff < 0
            return (
            <tr key={l.key} className={`border-b border-line/40 last:border-0 ${short ? 'bg-danger/5' : ''}`}>
              <td className="py-1.5 font-mono text-flame">{l.code}</td>
              <td>{l.name || '—'}</td>
              <td className="text-right tabular-nums">{l.q1}</td>
              <td className="text-right tabular-nums">{l.q2}</td>
              <td className="text-right tabular-nums">
                {short
                  ? <span className="text-danger font-medium">thiếu {-diff}</span>
                  : <span className="text-ok">đủ ✓</span>}
              </td>
            </tr>
          )})}
          {lines.length === 0 && (
            <tr><td colSpan={5} className="py-3 text-center text-txt-2">Không có dòng nào.</td></tr>
          )}
        </tbody>
        {lines.length > 0 && (
          <tfoot>
            <tr className="border-t border-line font-semibold">
              <td className="py-1.5" colSpan={2}>Tổng ({lines.length} dòng)</td>
              <td className="text-right tabular-nums">{totalQ1}</td>
              <td className="text-right tabular-nums">{totalQ2}</td>
              <td className="text-right tabular-nums">
                {totalQ2 - totalQ1 < 0
                  ? <span className="text-danger">thiếu {totalQ1 - totalQ2}</span>
                  : <span className="text-ok">đủ</span>}
              </td>
            </tr>
          </tfoot>
        )}
      </table>
    </Modal>
  )
}
