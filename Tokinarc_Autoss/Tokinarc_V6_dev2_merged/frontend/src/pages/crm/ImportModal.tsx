/**
 * Tokinarc frontend — src/pages/crm/ImportModal.tsx
 * Modal import dữ liệu cũ từ Excel/CSV (dùng chung: KH, Lead, Hợp đồng, Đơn).
 * Tải file mẫu → chọn file → Xem trước (dry-run) → Import. Chỉ manager/CEO/admin.
 */
import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Upload, Download, FileSpreadsheet, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'

interface Preview {
  total_rows: number
  will_create: number
  skipped_existing: number
  errors: { row: number; message: string }[]
}

export interface ImportSpec {
  title: string
  importUrl: string         // vd '/crm/customers/import/' hoặc '/crm/import/leads/'
  templateUrl: string
  templateFilename: string
  invalidateKey: string     // queryKey gốc cần làm mới sau import
  hint?: string
}

export function ImportModal({ open, onClose, spec }: { open: boolean; onClose: () => void; spec: ImportSpec }) {
  const qc = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState<'dry' | 'run' | 'tpl' | null>(null)

  const reset = () => { setFile(null); setPreview(null); setBusy(null); if (inputRef.current) inputRef.current.value = '' }
  const close = () => { reset(); onClose() }

  const downloadTemplate = async () => {
    setBusy('tpl')
    try {
      const res = await api.get(spec.templateUrl, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url; a.download = spec.templateFilename; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { toast.error(apiError(e)) } finally { setBusy(null) }
  }

  const submit = async (dry: boolean) => {
    if (!file) { toast.error('Chọn file Excel/CSV trước.'); return }
    setBusy(dry ? 'dry' : 'run')
    try {
      const fd = new FormData(); fd.append('file', file)
      const sep = spec.importUrl.includes('?') ? '&' : '?'
      const res = await api.post(`${spec.importUrl}${dry ? sep + 'dry_run=1' : ''}`, fd)
      if (dry) {
        setPreview(res.data)
      } else {
        toast.success(`Đã import ${res.data.created} bản ghi (bỏ qua ${res.data.skipped_existing} trùng).`)
        qc.invalidateQueries({ queryKey: [spec.invalidateKey] })
        close()
      }
    } catch (e) { toast.error(apiError(e)) } finally { setBusy(null) }
  }

  return (
    <Modal open={open} onClose={close} title={spec.title}
      icon={<Upload size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={close}>Đóng</Button>
          <Button variant="ghost" onClick={() => submit(true)} disabled={!file || busy !== null}>
            {busy === 'dry' ? <Loader2 size={14} className="animate-spin" /> : null} Xem trước
          </Button>
          <Button onClick={() => submit(false)} disabled={!file || busy !== null || preview?.will_create === 0}>
            {busy === 'run' ? <Loader2 size={14} className="animate-spin" /> : null} Import
          </Button>
        </>
      }>
      <div className="space-y-3">
        <p className="text-xs text-txt-2">
          Tải file mẫu, điền dữ liệu cũ, rồi tải lên. Hỗ trợ <b>.xlsx</b> và <b>.csv</b>.
          Bản ghi trùng mã sẽ được bỏ qua. {spec.hint}
        </p>

        <button onClick={downloadTemplate} disabled={busy !== null}
          className="flex items-center gap-2 text-sm text-flame hover:underline disabled:opacity-50">
          {busy === 'tpl' ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
          Tải file mẫu (Excel)
        </button>

        <div>
          <button type="button" onClick={() => inputRef.current?.click()}
            className="flex items-center gap-2 bg-ink-3 border border-line rounded-md px-3 py-2 text-sm
                       text-txt-2 hover:border-flame hover:text-txt transition-colors w-full">
            <FileSpreadsheet size={15} className="text-flame" />
            {file ? file.name : 'Chọn file Excel/CSV…'}
          </button>
          <input ref={inputRef} type="file" accept=".xlsx,.csv" className="hidden"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null) }} />
        </div>

        {preview && (
          <div className="border border-line rounded-md p-3 text-sm space-y-2 bg-ink-3/40">
            <div className="flex items-center gap-4 flex-wrap">
              <span className="flex items-center gap-1 text-green-400">
                <CheckCircle2 size={14} /> Sẽ tạo: <b>{preview.will_create}</b>
              </span>
              <span className="text-txt-2">Bỏ qua (trùng): {preview.skipped_existing}</span>
              <span className="text-txt-2">Tổng dòng: {preview.total_rows}</span>
            </div>
            {preview.errors.length > 0 && (
              <div className="text-xs text-danger">
                <div className="flex items-center gap-1 mb-1"><AlertTriangle size={13} /> {preview.errors.length} dòng lỗi:</div>
                <ul className="space-y-0.5 max-h-28 overflow-y-auto">
                  {preview.errors.slice(0, 20).map((er, i) => (<li key={i}>• Dòng {er.row}: {er.message}</li>))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}
