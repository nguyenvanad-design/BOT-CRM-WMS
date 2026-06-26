/**
 * Tokinarc frontend — src/pages/crm/QuoteDetailModal.tsx
 * Xem chi tiết báo giá (read-only) trước khi duyệt: thông tin chung + bảng dòng
 * hàng + tổng giá trị + ghi chú. Dữ liệu lấy từ chính object Quote (đã có lines).
 */
import type { ReactNode } from 'react'
import { FileText } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { Tag, Button } from '@/components/ui'
import { formatVnd, formatDate, QUOTE_STATUS_LABEL, QUOTE_STATUS_TONE } from '@/lib/crm'
import type { Quote } from '@/lib/types'

export function QuoteDetailModal({ quote, open, onClose, footer }: {
  quote: Quote | null; open: boolean; onClose: () => void; footer?: ReactNode
}) {
  return (
    <Modal open={open} onClose={onClose} wide
      title={quote ? `Báo giá ${quote.code}` : 'Báo giá'}
      icon={<FileText size={18} className="text-flame" />}
      footer={footer ?? <Button variant="ghost" onClick={onClose}>Đóng</Button>}>
      {quote && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Info label="Khách hàng" value={quote.customer_name} />
            <Info label="Người lập" value={quote.owner_username} />
            <Info label="Trạng thái"
              value={<Tag tone={QUOTE_STATUS_TONE[quote.status]}>{QUOTE_STATUS_LABEL[quote.status]}</Tag>} />
            <Info label="Hạn hiệu lực" value={formatDate(quote.valid_until ?? quote.due_date)} />
          </div>

          <div>
            <div className="text-xs text-txt-2 mb-1.5">Chi tiết dòng hàng</div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-txt-2 text-[11px] uppercase tracking-wide">
                  <th className="text-left py-1.5">Mã</th>
                  <th className="text-left">Tên</th>
                  <th className="text-right">SL</th>
                  <th className="text-right">Đơn giá</th>
                  <th className="text-right">Thành tiền</th>
                </tr>
              </thead>
              <tbody>
                {quote.lines.map((l, i) => (
                  <tr key={l.id ?? i} className="border-b border-line/40 last:border-0">
                    <td className="py-1.5 font-mono text-flame">{l.part_no}</td>
                    <td>{l.part_name}</td>
                    <td className="text-right tabular-nums">{l.qty}</td>
                    <td className="text-right tabular-nums">{formatVnd(l.unit_price_vnd)}</td>
                    <td className="text-right tabular-nums">
                      {formatVnd(l.line_total_vnd ?? Number(l.unit_price_vnd) * l.qty)}
                    </td>
                  </tr>
                ))}
                {quote.lines.length === 0 && (
                  <tr><td colSpan={5} className="py-3 text-center text-txt-2">Không có dòng nào.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="border-t border-line pt-3 space-y-0.5 text-sm">
            {Number(quote.discount_pct) > 0 && (
              <>
                <div className="flex justify-end gap-3">
                  <span className="text-txt-2">Tạm tính:</span>
                  <span className="tabular-nums w-32 text-right">{formatVnd(quote.subtotal_vnd ?? 0)}</span>
                </div>
                <div className="flex justify-end gap-3">
                  <span className="text-txt-2">Chiết khấu {quote.discount_pct}%:</span>
                  <span className="tabular-nums w-32 text-right text-warn">
                    −{formatVnd((quote.subtotal_vnd ?? 0) - Number(quote.total_vnd))}
                  </span>
                </div>
              </>
            )}
            <div className="flex justify-end items-baseline gap-3">
              <span className="text-txt-2">Tổng giá trị:</span>
              <span className="font-bold text-flame tabular-nums text-base w-32 text-right">{formatVnd(quote.total_vnd)}</span>
            </div>
          </div>

          {/* Lãi gộp — CHỈ manager/CEO (server chỉ trả 'margin' cho cấp quản lý) */}
          {quote.margin && (
            <div className="border-t border-line pt-3">
              <div className="text-[11px] uppercase tracking-wide text-txt-2 mb-1.5">
                Lãi gộp (chỉ quản lý/CEO xem)
              </div>
              <div className="grid grid-cols-3 gap-3 text-sm">
                <MBox label="Giá vốn" value={formatVnd(quote.margin.cost_total_vnd)} />
                <MBox label="Lãi gộp" value={formatVnd(quote.margin.margin_vnd)}
                  danger={quote.margin.margin_vnd < 0} />
                <MBox label="Biên LN" value={quote.margin.margin_pct != null ? `${quote.margin.margin_pct}%` : '—'}
                  danger={(quote.margin.margin_pct ?? 0) < 0} />
              </div>
              {quote.margin.margin_vnd < 0 && (
                <p className="text-[11px] text-danger mt-1.5">⚠ Báo giá đang BÁN DƯỚI GIÁ VỐN (lỗ).</p>
              )}
              {quote.margin.missing_cost_lines > 0 && (
                <p className="text-[11px] text-warn mt-1.5">
                  ⚠ {quote.margin.missing_cost_lines} dòng chưa có giá vốn — lãi gộp chưa đầy đủ.
                </p>
              )}
            </div>
          )}

          {quote.payment_terms_note && (
            <div>
              <div className="text-xs text-txt-2 mb-1">Điều khoản thanh toán</div>
              <p className="text-sm bg-flame/10 border border-flame/30 text-txt rounded-md px-3 py-2 whitespace-pre-wrap">
                {quote.payment_terms_note}
              </p>
            </div>
          )}
          {quote.notes && (
            <div>
              <div className="text-xs text-txt-2 mb-1">Ghi chú</div>
              <p className="text-sm bg-ink-3 rounded-md px-3 py-2 whitespace-pre-wrap">{quote.notes}</p>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}

function MBox({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="bg-ink-3 rounded-md px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-txt-2">{label}</div>
      <div className={`font-semibold tabular-nums ${danger ? 'text-danger' : 'text-ok'}`}>{value}</div>
    </div>
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
