/**
 * Tokinarc frontend — src/components/form.tsx
 * Primitive form field bám theme, forwardRef để dùng trực tiếp với
 * react-hook-form `register()`. Mỗi field có label + thông báo lỗi.
 */
import { forwardRef, type ReactNode } from 'react'

const LABEL = 'block text-[11px] font-semibold uppercase tracking-wide text-txt-2 mb-1'
const BASE =
  'w-full bg-ink-3 border border-line rounded-md px-2.5 py-2 text-sm text-txt ' +
  'focus:outline-none focus:border-flame transition-colors disabled:opacity-60'

export function FieldRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">{children}</div>
}

function Wrap({ label, error, full, children }: {
  label: string; error?: string; full?: boolean; children: ReactNode
}) {
  return (
    <div className={full ? 'col-span-2 mb-3' : ''}>
      <label className={LABEL}>{label}</label>
      {children}
      {error && <p className="text-danger text-[11px] mt-1">{error}</p>}
    </div>
  )
}

export const TextInput = forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; full?: boolean }
>(function TextInput({ label, error, full, ...props }, ref) {
  return (
    <Wrap label={label} error={error} full={full}>
      <input ref={ref} {...props} className={BASE} />
    </Wrap>
  )
})

export const TextArea = forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; error?: string }
>(function TextArea({ label, error, ...props }, ref) {
  return (
    <Wrap label={label} error={error} full>
      <textarea ref={ref} {...props} className={`${BASE} min-h-[70px] resize-y`} />
    </Wrap>
  )
})

export interface Option { value: string; label: string }

export const SelectInput = forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement> & {
    label: string; error?: string; full?: boolean; options: Option[]; placeholder?: string
  }
>(function SelectInput({ label, error, full, options, placeholder, ...props }, ref) {
  return (
    <Wrap label={label} error={error} full={full}>
      <select ref={ref} {...props} className={BASE}>
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Wrap>
  )
})
