/**
 * Tokinarc frontend — src/components/Modal.tsx
 * Modal overlay dùng chung cho form tạo/sửa. Đóng bằng nút X, click nền, hoặc Esc.
 */
import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'

export function Modal({
  open, onClose, title, icon, children, footer, wide,
}: {
  open: boolean
  onClose: () => void
  title: string
  icon?: ReactNode
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className={`bg-ink-2 border border-line rounded-xl flex flex-col max-h-[88vh] w-full ${wide ? 'max-w-3xl' : 'max-w-xl'}`}>
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-line shrink-0">
          {icon}
          <h2 className="text-[15px] font-bold">{title}</h2>
          <button
            onClick={onClose}
            className="ml-auto text-txt-2 hover:text-txt hover:bg-ink-3 rounded p-1 transition-colors"
            aria-label="Đóng"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-5 py-4 overflow-y-auto flex-1">{children}</div>
        {footer && (
          <div className="px-5 py-3 border-t border-line flex justify-end gap-2 shrink-0">{footer}</div>
        )}
      </div>
    </div>
  )
}
