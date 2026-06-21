/**
 * Tokinarc frontend — src/pages/wms/Scan.tsx
 * Quét barcode/QR bằng camera điện thoại (@zxing/library) — 3 chế độ:
 *   - Tra cứu: quét → tìm phụ tùng (catalog) + serial (WMS).
 *   - Nhập kho: quét mã hàng + ô (bin) + SL → cộng tồn (POST scan-entry receive).
 *   - Kiểm kê: quét mã hàng + ô + số đếm → set tồn (POST scan-entry count).
 * Có ô nhập tay khi không dùng được camera.
 */
import { useEffect, useRef, useState } from 'react'
import { BrowserMultiFormatReader } from '@zxing/library'
import { ScanLine, Camera, CameraOff, Search, PackagePlus, ClipboardCheck } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { compactVnd } from '@/lib/crm'
import { SERIAL_STATUS_LABEL, SERIAL_STATUS_TONE } from '@/lib/wms'
import type { CatalogPart, SerialNumber } from '@/lib/types'
import { Card, PageHeader, Button, Tag } from '@/components/ui'

type Mode = 'lookup' | 'receive' | 'count'
type Target = 'code' | 'bin'
interface LookupResult { code: string; parts: CatalogPart[]; serials: SerialNumber[] }
interface EntryLog { text: string; ok: boolean }

const MODES: { key: Mode; label: string; icon: typeof Search }[] = [
  { key: 'lookup', label: 'Tra cứu', icon: Search },
  { key: 'receive', label: 'Nhập kho', icon: PackagePlus },
  { key: 'count', label: 'Kiểm kê', icon: ClipboardCheck },
]

export function ScanPage() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const readerRef = useRef<BrowserMultiFormatReader | null>(null)
  const [mode, setMode] = useState<Mode>('lookup')
  const [scanning, setScanning] = useState(false)
  const [camError, setCamError] = useState('')
  const [busy, setBusy] = useState(false)

  // Tra cứu
  const [manual, setManual] = useState('')
  const [result, setResult] = useState<LookupResult | null>(null)
  // Nhập kho / Kiểm kê
  const [target, setTarget] = useState<Target>('code')
  const [code, setCode] = useState('')
  const [binCode, setBinCode] = useState('')
  const [qty, setQty] = useState('')
  const [log, setLog] = useState<EntryLog[]>([])

  const stop = () => { readerRef.current?.reset(); setScanning(false) }
  useEffect(() => () => { readerRef.current?.reset() }, [])

  const lookup = async (c: string) => {
    const q = c.trim(); if (!q) return
    setBusy(true)
    try {
      const [parts, serials] = await Promise.all([
        api.get<{ results: CatalogPart[] }>('/catalog/parts/', { params: { search: q } }),
        api.get<{ results: SerialNumber[] }>('/wms/serials/', { params: { search: q } }),
      ])
      setResult({ code: q, parts: parts.data.results.slice(0, 5), serials: serials.data.results.slice(0, 5) })
    } catch (e) { setResult({ code: q, parts: [], serials: [] }); apiError(e) } finally { setBusy(false) }
  }

  // Nhận 1 mã quét/nhập theo chế độ + đích đang quét
  const onCode = (text: string) => {
    if (mode === 'lookup') { setManual(text); lookup(text); return }
    if (target === 'code') setCode(text); else setBinCode(text)
  }

  const submitEntry = async () => {
    if (!code || !binCode || !qty) { toast.error('Cần mã hàng, mã ô và số lượng.'); return }
    setBusy(true)
    try {
      const res = await api.post('/wms/inventory/scan-entry/', {
        code: code.trim(), bin_code: binCode.trim(), qty: Number(qty), mode,
      })
      toast.success(res.data.detail)
      setLog((l) => [{ text: `${res.data.part_no} @ ${res.data.bin_code} → tồn ${res.data.qty_on_hand}`, ok: true }, ...l].slice(0, 8))
      setCode(''); setQty(''); setTarget('code')   // giữ binCode để quét tiếp cùng ô
    } catch (e) {
      const m = apiError(e); toast.error(m)
      setLog((l) => [{ text: m, ok: false }, ...l].slice(0, 8))
    } finally { setBusy(false) }
  }

  const start = async () => {
    setCamError(''); setResult(null)
    const reader = new BrowserMultiFormatReader()
    readerRef.current = reader; setScanning(true)
    try {
      await reader.decodeFromVideoDevice(null, videoRef.current!, (res) => {
        if (res) {
          const text = res.getText()
          onCode(text)
          if (mode === 'lookup') stop()   // tra cứu: quét 1 lần; nhập/kiểm kê: quét liên tục
        }
      })
    } catch (e) {
      setCamError(e instanceof Error ? e.message : 'Không mở được camera.'); setScanning(false)
    }
  }

  const entryMode = mode === 'receive' || mode === 'count'

  return (
    <div className="max-w-2xl">
      <PageHeader icon={<ScanLine size={20} className="text-flame" />} title="Quét mã"
        subtitle="Quét bằng điện thoại: tra cứu, nhập kho, kiểm kê" />

      {/* Chọn chế độ */}
      <div className="flex gap-1.5 mb-4">
        {MODES.map((m) => {
          const Icon = m.icon
          return (
            <button key={m.key} onClick={() => { setMode(m.key); setResult(null) }}
              className={`flex-1 flex items-center justify-center gap-1.5 text-sm rounded-md py-2 border transition-colors ${
                mode === m.key ? 'bg-flame/15 text-flame border-flame/40' : 'border-line text-txt-2 hover:text-txt'
              }`}>
              <Icon size={15} /> {m.label}
            </button>
          )
        })}
      </div>

      <Card className="mb-4">
        <div className="aspect-video bg-ink rounded-lg overflow-hidden mb-3 grid place-items-center relative">
          <video ref={videoRef} className={`w-full h-full object-cover ${scanning ? '' : 'hidden'}`} />
          {!scanning && <div className="text-txt-2 text-sm flex flex-col items-center gap-2"><Camera size={28} /> Camera tắt</div>}
          {scanning && <div className="absolute inset-x-8 top-1/2 h-0.5 bg-flame/70 animate-pulse" />}
        </div>
        {camError && <p className="text-danger text-xs mb-2">{camError}</p>}

        {/* Khi nhập/kiểm kê: chọn đang quét vào ô nào */}
        {entryMode && (
          <div className="flex gap-1.5 mb-3 text-xs">
            <span className="text-txt-2 self-center">Đang quét vào:</span>
            <button onClick={() => setTarget('code')}
              className={`rounded-full px-2.5 py-1 border ${target === 'code' ? 'border-flame text-flame' : 'border-line text-txt-2'}`}>Mã hàng</button>
            <button onClick={() => setTarget('bin')}
              className={`rounded-full px-2.5 py-1 border ${target === 'bin' ? 'border-flame text-flame' : 'border-line text-txt-2'}`}>Ô (bin)</button>
          </div>
        )}

        <div className="flex gap-2">
          {!scanning
            ? <Button onClick={start}><Camera size={15} /> Bắt đầu quét</Button>
            : <Button variant="danger" onClick={stop}><CameraOff size={15} /> Dừng</Button>}
        </div>

        {/* Tra cứu: ô nhập tay */}
        {mode === 'lookup' && (
          <div className="flex gap-2 mt-3 pt-3 border-t border-line">
            <input value={manual} onChange={(e) => setManual(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') lookup(manual) }}
              placeholder="Hoặc nhập mã tay…"
              className="flex-1 bg-ink-3 border border-line rounded-md px-3 py-2 text-sm focus:border-flame focus:outline-none" />
            <Button variant="ghost" onClick={() => lookup(manual)} disabled={busy}><Search size={15} /> Tra</Button>
          </div>
        )}

        {/* Nhập kho / Kiểm kê: form */}
        {entryMode && (
          <div className="mt-3 pt-3 border-t border-line space-y-2">
            <Field label="Mã hàng" value={code} onChange={setCode} placeholder="Quét hoặc nhập mã phụ tùng" />
            <Field label="Mã ô (bin)" value={binCode} onChange={setBinCode} placeholder="VD HCM-A-R01-B03" />
            <Field label={mode === 'receive' ? 'Số lượng nhập' : 'Số đếm thực tế'} value={qty}
              onChange={setQty} placeholder="0" type="number" />
            <Button onClick={submitEntry} disabled={busy}>
              {mode === 'receive' ? <><PackagePlus size={15} /> Nhập kho</> : <><ClipboardCheck size={15} /> Cập nhật tồn</>}
            </Button>
          </div>
        )}
      </Card>

      {/* Nhật ký nhập/kiểm kê */}
      {entryMode && log.length > 0 && (
        <Card className="mb-4">
          <div className="text-sm font-semibold mb-2">Vừa xử lý</div>
          <ul className="space-y-1 text-sm">
            {log.map((l, i) => (
              <li key={i} className={l.ok ? 'text-txt' : 'text-danger'}>{l.ok ? '✓' : '✕'} {l.text}</li>
            ))}
          </ul>
        </Card>
      )}

      {/* Kết quả tra cứu */}
      {mode === 'lookup' && result && (
        <Card>
          <div className="text-sm mb-3">Kết quả cho <span className="font-mono text-flame">{result.code}</span></div>
          {result.parts.length === 0 && result.serials.length === 0 && (
            <p className="text-txt-2 text-sm">Không tìm thấy phụ tùng/serial khớp.</p>
          )}
          {result.parts.length > 0 && (
            <div className="mb-3">
              <div className="text-xs text-txt-2 mb-1.5">Phụ tùng</div>
              <div className="space-y-1.5">
                {result.parts.map((p) => (
                  <div key={p.tokin_part_no} className="flex items-center gap-2 border border-line rounded-md px-3 py-2 text-sm">
                    <span className="font-mono text-flame">{p.tokin_part_no}</span>
                    <span className="flex-1">{p.display_name_vi}</span>
                    <span className="text-txt-2">{p.is_contact_price ? 'Liên hệ' : compactVnd(p.effective_price_vnd)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {result.serials.length > 0 && (
            <div>
              <div className="text-xs text-txt-2 mb-1.5">Serial</div>
              <div className="space-y-1.5">
                {result.serials.map((s) => (
                  <div key={s.id} className="flex items-center gap-2 border border-line rounded-md px-3 py-2 text-sm">
                    <span className="font-mono text-flame">{s.serial}</span>
                    <span className="flex-1">{s.torch}</span>
                    <Tag tone={SERIAL_STATUS_TONE[s.status]}>{SERIAL_STATUS_LABEL[s.status]}</Tag>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

function Field({ label, value, onChange, placeholder, type = 'text' }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string
}) {
  return (
    <div>
      <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} type={type}
        className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm focus:border-flame focus:outline-none" />
    </div>
  )
}
