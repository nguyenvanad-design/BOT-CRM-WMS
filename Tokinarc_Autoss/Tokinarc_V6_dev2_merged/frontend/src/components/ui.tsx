/**
 * Tokinarc frontend — src/components/ui.tsx
 * Bộ UI dùng chung cho các trang CRM/WMS/CEO. Bám theme thép + lửa hàn
 * (ink/line/flame/ok/warn/danger) và phong cách mockup HTML gốc.
 */
import type { ReactNode } from 'react'
import { TAG_CLASS, type TagTone } from '@/lib/crm'

// ── Card ──────────────────────────────────────────────────────────────────
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`bg-ink-2 border border-line rounded-lg p-4 ${className}`}>{children}</div>
  )
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-sm font-semibold">{children}</h2>
      {action}
    </div>
  )
}

// ── KPI / Stat ────────────────────────────────────────────────────────────
export function StatCard({
  label, value, delta, tone = 'flame', onClick,
}: {
  label: string
  value: ReactNode
  delta?: ReactNode
  tone?: TagTone | 'txt'
  onClick?: () => void
}) {
  const valTone: Record<string, string> = {
    flame: 'text-flame', ok: 'text-ok', warn: 'text-warn', danger: 'text-danger',
    blue: 'text-sky-400', purple: 'text-purple-400', gray: 'text-txt-2', txt: 'text-txt',
  }
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className={`text-left bg-ink-2 border border-line rounded-lg p-4 transition-colors w-full
                  ${onClick ? 'hover:border-flame cursor-pointer' : 'cursor-default'}`}
    >
      <div className={`text-2xl font-bold tabular-nums ${valTone[tone] ?? 'text-txt'}`}>{value}</div>
      <div className="text-[11px] text-txt-2 mt-0.5">{label}</div>
      {delta && <div className="text-[11px] mt-1">{delta}</div>}
    </button>
  )
}

// ── Tag ───────────────────────────────────────────────────────────────────
export function Tag({ tone = 'gray', children }: { tone?: TagTone; children: ReactNode }) {
  return (
    <span className={`inline-block text-[10px] font-semibold border rounded-full px-2 py-0.5 ${TAG_CLASS[tone]}`}>
      {children}
    </span>
  )
}

// ── Page header ───────────────────────────────────────────────────────────
export function PageHeader({
  icon, title, subtitle, actions,
}: {
  icon?: ReactNode; title: string; subtitle?: ReactNode; actions?: ReactNode
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-5">
      <div>
        <h1 className="text-lg font-semibold flex items-center gap-2">
          {icon}
          {title}
        </h1>
        {subtitle && <p className="text-xs text-txt-2 mt-0.5">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  )
}

// ── Search input ──────────────────────────────────────────────────────────
import { Search } from 'lucide-react'
export function SearchInput({
  value, onChange, placeholder = 'Tìm…',
}: {
  value: string; onChange: (v: string) => void; placeholder?: string
}) {
  return (
    <div className="relative w-full sm:w-auto">
      <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-txt-2" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="bg-ink-2 border border-line rounded-md pl-9 pr-3 py-2 text-sm w-full sm:w-64
                   focus:border-flame transition-colors"
      />
    </div>
  )
}

// ── Buttons ───────────────────────────────────────────────────────────────
type BtnVariant = 'primary' | 'ghost' | 'success' | 'danger'
const BTN_CLASS: Record<BtnVariant, string> = {
  primary: 'bg-flame hover:bg-flame-hi text-white',
  ghost:   'bg-transparent border border-line text-txt-2 hover:bg-ink-3 hover:text-txt',
  success: 'bg-ok/90 hover:bg-ok text-white',
  danger:  'bg-danger/90 hover:bg-danger text-white',
}
export function Button({
  variant = 'primary', size = 'md', className = '', ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: 'sm' | 'md' }) {
  const pad = size === 'sm' ? 'px-2.5 py-1 text-[11px]' : 'px-3.5 py-2 text-xs'
  return (
    <button
      {...props}
      className={`inline-flex items-center gap-1.5 rounded-md font-medium transition-colors
                  disabled:opacity-50 disabled:cursor-not-allowed ${BTN_CLASS[variant]} ${pad} ${className}`}
    />
  )
}

// ── Table chrome ──────────────────────────────────────────────────────────
export function TableCard({ children }: { children: ReactNode }) {
  return (
    <div className="border border-line rounded-lg overflow-x-auto bg-ink-2">
      <table className="w-full min-w-[560px] text-sm">{children}</table>
    </div>
  )
}

export function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <th className={`px-4 py-2.5 text-left font-medium text-xs text-txt-2 ${className}`}>{children}</th>
}

export function Td({ children, className = '', onClick }: {
  children?: ReactNode
  className?: string
  onClick?: React.MouseEventHandler<HTMLTableCellElement>
}) {
  return <td className={`px-4 py-2.5 ${className}`} onClick={onClick}>{children}</td>
}

/** Hàng thông báo (loading/empty/error) trải full bảng. */
export function RowMsg({ colSpan, danger, children }: {
  colSpan: number; danger?: boolean; children: ReactNode
}) {
  return (
    <tr>
      <td colSpan={colSpan} className={`px-4 py-10 text-center text-sm ${danger ? 'text-danger' : 'text-txt-2'}`}>
        {children}
      </td>
    </tr>
  )
}

// ── Gauge (thanh xác suất) ────────────────────────────────────────────────
export function Gauge({ pct, tone = 'flame' }: { pct: number; tone?: TagTone }) {
  const bar: Record<string, string> = {
    flame: 'bg-flame', ok: 'bg-ok', warn: 'bg-warn', danger: 'bg-danger',
    blue: 'bg-sky-400', purple: 'bg-purple-400', gray: 'bg-txt-2',
  }
  const clamped = Math.max(0, Math.min(100, pct))
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-ink-3 rounded-full overflow-hidden min-w-[48px]">
        <div className={`h-full rounded-full ${bar[tone] ?? 'bg-flame'}`} style={{ width: `${clamped}%` }} />
      </div>
      <span className="text-xs tabular-nums text-txt-2 w-9 text-right">{clamped}%</span>
    </div>
  )
}

// ── Pagination ────────────────────────────────────────────────────────────
export function Pagination({
  page, totalPages, fetching, onPrev, onNext,
}: {
  page: number; totalPages: number; fetching?: boolean
  onPrev: () => void; onNext: () => void
}) {
  return (
    <div className="flex items-center justify-between mt-3 text-sm">
      <span className="text-txt-2 text-xs">
        Trang {page}/{totalPages} {fetching && '· đang tải…'}
      </span>
      <div className="flex gap-2">
        <Button variant="ghost" size="sm" disabled={page <= 1} onClick={onPrev}>Trước</Button>
        <Button variant="ghost" size="sm" disabled={page >= totalPages} onClick={onNext}>Sau</Button>
      </div>
    </div>
  )
}
