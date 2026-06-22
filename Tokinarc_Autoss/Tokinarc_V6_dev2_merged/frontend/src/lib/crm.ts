/**
 * Tokinarc frontend — src/lib/crm.ts
 * Bảng nhãn (label) + style tag cho các enum CRM, và helper định dạng tiền VND.
 * Nhãn khớp TextChoices ở backend (apps/crm/models.py).
 */
import type {
  LeadStatus, OppStage, QuoteStatus, TicketStatus, TicketPriority,
} from '@/lib/types'

/** Màu tag — khớp tiện ích Tailwind theme (ink/flame/ok/warn/danger…). */
export type TagTone = 'ok' | 'warn' | 'danger' | 'flame' | 'blue' | 'purple' | 'gray'

export const TAG_CLASS: Record<TagTone, string> = {
  ok:     'text-ok border-ok/30 bg-ok/10',
  warn:   'text-warn border-warn/30 bg-warn/10',
  danger: 'text-danger border-danger/30 bg-danger/10',
  flame:  'text-flame border-flame/30 bg-flame/10',
  blue:   'text-sky-400 border-sky-400/30 bg-sky-400/10',
  purple: 'text-purple-400 border-purple-400/30 bg-purple-400/10',
  gray:   'text-txt-2 border-line bg-ink-3',
}

// ── Customer ──────────────────────────────────────────────────────────────
export const SEGMENT_LABEL: Record<string, string> = {
  factory: 'Nhà máy SX', integrator: 'Robot Integrator', dealer: 'Đại lý',
  oem: 'OEM', shipyard: 'Đóng tàu', other: 'Khác',
}
export const SEGMENT_TONE: Record<string, TagTone> = {
  factory: 'blue', integrator: 'purple', dealer: 'warn',
  oem: 'flame', shipyard: 'gray', other: 'gray',
}

export const CUSTOMER_STATUS_LABEL: Record<string, string> = {
  new: 'Mới', potential: 'Tiềm năng', vip: 'VIP',
  normal: 'Bình thường', inactive: 'Không hoạt động',
}
export const CUSTOMER_STATUS_TONE: Record<string, TagTone> = {
  new: 'blue', potential: 'flame', vip: 'ok', normal: 'gray', inactive: 'gray',
}

// ── Lead ──────────────────────────────────────────────────────────────────
export const LEAD_STATUS_LABEL: Record<LeadStatus, string> = {
  new: 'Mới', contacted: 'Đã liên hệ', qualified: 'Đủ điều kiện',
  converted: 'Đã chuyển', lost: 'Thất bại',
}
export const LEAD_STATUS_TONE: Record<LeadStatus, TagTone> = {
  new: 'warn', contacted: 'blue', qualified: 'ok', converted: 'purple', lost: 'gray',
}
/** Nguồn lead — khớp LeadSource (backend). */
export const LEAD_SOURCE_LABEL: Record<string, string> = {
  exhibition: 'Triển lãm / Hội chợ', referral: 'Giới thiệu',
  chatbot_khach: 'Website / Bot khách', chatbot: 'Trợ lý nội bộ',
  zalo: 'Zalo', facebook_ads: 'Facebook Ads', google_ads: 'Google Ads',
  telesales: 'Telesales', dealer: 'Đại lý / NPP', manual: 'Nhập tay', other: 'Khác',
}
/** Điểm lead 0-100 → tone. */
export const leadScoreTone = (s: number): TagTone =>
  s >= 80 ? 'ok' : s >= 50 ? 'warn' : 'gray'

// ── Opportunity ───────────────────────────────────────────────────────────
export const OPP_STAGE_LABEL: Record<OppStage, string> = {
  prospect: 'Tiếp cận', qualify: 'Thẩm định', proposal: 'Đề xuất',
  negotiate: 'Đàm phán', won: 'Thắng', lost: 'Thua',
}
export const OPP_STAGE_TONE: Record<OppStage, TagTone> = {
  prospect: 'gray', qualify: 'blue', proposal: 'blue',
  negotiate: 'warn', won: 'ok', lost: 'danger',
}
/** Thứ tự cột kanban pipeline (bỏ lost ra cuối). */
export const OPP_STAGE_ORDER: OppStage[] =
  ['prospect', 'qualify', 'proposal', 'negotiate', 'won', 'lost']

// ── Quote ─────────────────────────────────────────────────────────────────
export const QUOTE_STATUS_LABEL: Record<QuoteStatus, string> = {
  draft: 'Nháp', sent: 'Đã gửi', pending_ceo: 'Chờ CEO duyệt', approved: 'Đã duyệt',
  rejected: 'Từ chối', converted: 'Đã chuyển HĐ', expired: 'Hết hạn',
}
export const QUOTE_STATUS_TONE: Record<QuoteStatus, TagTone> = {
  draft: 'gray', sent: 'blue', pending_ceo: 'warn', approved: 'ok',
  rejected: 'danger', converted: 'purple', expired: 'danger',
}

// ── Ticket ────────────────────────────────────────────────────────────────
export const TICKET_STATUS_LABEL: Record<TicketStatus, string> = {
  open: 'Mở', in_progress: 'Đang xử lý', resolved: 'Đã giải quyết', closed: 'Đóng',
}
export const TICKET_STATUS_TONE: Record<TicketStatus, TagTone> = {
  open: 'blue', in_progress: 'warn', resolved: 'ok', closed: 'gray',
}
export const TICKET_PRIORITY_LABEL: Record<TicketPriority, string> = {
  low: 'Thấp', medium: 'Trung bình', high: 'Cao', urgent: 'Khẩn',
}
export const TICKET_PRIORITY_TONE: Record<TicketPriority, TagTone> = {
  low: 'gray', medium: 'blue', high: 'warn', urgent: 'danger',
}

// ── Contract ──────────────────────────────────────────────────────────────
export const CONTRACT_STATUS_LABEL: Record<string, string> = {
  draft: 'Nháp', pending_sign: 'Chờ ký', active: 'Hiệu lực',
  expired: 'Hết hạn', cancelled: 'Hủy',
}
export const CONTRACT_STATUS_TONE: Record<string, TagTone> = {
  draft: 'gray', pending_sign: 'warn', active: 'ok', expired: 'danger', cancelled: 'gray',
}

// ── Activity ──────────────────────────────────────────────────────────────
export const ACTIVITY_TYPE_LABEL: Record<string, string> = {
  call: 'Gọi điện', email: 'Email', meeting: 'Gặp mặt', zalo: 'Zalo', other: 'Khác',
}
export const ACTIVITY_TYPE_TONE: Record<string, TagTone> = {
  call: 'ok', email: 'blue', meeting: 'flame', zalo: 'purple', other: 'gray',
}

// ── Tiền VND ──────────────────────────────────────────────────────────────
/** "₫ 2.470.000.000" — đầy đủ, dùng ở detail. */
export function formatVnd(amount: string | number | null | undefined): string {
  if (amount === null || amount === undefined || amount === '') return '—'
  const n = typeof amount === 'string' ? Number(amount) : amount
  if (!Number.isFinite(n)) return '—'
  return '₫ ' + Math.round(n).toLocaleString('vi-VN')
}

/** "2.47 tỷ" / "185 tr" — gọn, dùng ở KPI/bảng giống mockup. */
export function compactVnd(amount: string | number | null | undefined): string {
  if (amount === null || amount === undefined || amount === '') return '—'
  const n = typeof amount === 'string' ? Number(amount) : amount
  if (!Number.isFinite(n)) return '—'
  const abs = Math.abs(n)
  if (abs >= 1e9) return `₫ ${(n / 1e9).toFixed(2).replace(/\.?0+$/, '')} tỷ`
  if (abs >= 1e6) return `₫ ${Math.round(n / 1e6)} tr`
  if (abs >= 1e3) return `₫ ${Math.round(n / 1e3)}k`
  return '₫ ' + Math.round(n).toLocaleString('vi-VN')
}

/** Ngày ISO → "dd/MM/yyyy" (an toàn null). */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
