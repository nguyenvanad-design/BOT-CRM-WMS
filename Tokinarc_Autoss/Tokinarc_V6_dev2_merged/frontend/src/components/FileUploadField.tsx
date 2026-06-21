/**
 * Tokinarc frontend — src/components/FileUploadField.tsx
 * Ô chọn + tải 1 file lên storage. Dùng cho ghi âm / file recap trên Visit & Activity.
 * Báo trạng thái đang tải, hiện tên file đã tải, cho gỡ.
 */
import { useRef, useState } from 'react'
import { Paperclip, Loader2, X } from 'lucide-react'
import { toast } from 'sonner'
import { uploadFile, type UploadedFile } from '@/lib/upload'
import { apiError } from '@/lib/api'

interface Props {
  label: string
  kind: string                       // storage kind, vd 'visit_recording'
  accept?: string                    // vd 'audio/*'
  value: UploadedFile | null
  onChange: (f: UploadedFile | null) => void
}

export function FileUploadField({ label, kind, accept, value, onChange }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)

  const pick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy(true)
    try {
      onChange(await uploadFile(file, kind))
    } catch (err) {
      toast.error(apiError(err))
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className="mb-3">
      <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">{label}</label>
      {value ? (
        <div className="flex items-center gap-2 bg-ink-3 border border-line rounded-md px-3 py-2 text-sm">
          <Paperclip size={14} className="text-flame shrink-0" />
          <span className="flex-1 truncate">{value.filename}</span>
          <button type="button" onClick={() => onChange(null)}
            className="text-txt-2 hover:text-danger p-0.5" aria-label="Gỡ file"><X size={14} /></button>
        </div>
      ) : (
        <>
          <button type="button" onClick={() => inputRef.current?.click()} disabled={busy}
            className="flex items-center gap-2 bg-ink-3 border border-line rounded-md px-3 py-2 text-sm
                       text-txt-2 hover:border-flame hover:text-txt transition-colors disabled:opacity-50">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Paperclip size={14} />}
            {busy ? 'Đang tải…' : 'Chọn file'}
          </button>
          <input ref={inputRef} type="file" accept={accept} onChange={pick} className="hidden" />
        </>
      )}
    </div>
  )
}
