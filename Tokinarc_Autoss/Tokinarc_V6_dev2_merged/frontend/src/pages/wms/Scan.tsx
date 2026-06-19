/**
 * Tokinarc frontend — src/pages/wms/Scan.tsx
 * Quét mã vạch/QR bằng camera (@zxing/library) → tra cứu phụ tùng (catalog) +
 * serial (WMS). Có ô nhập tay khi không dùng được camera.
 */
import { useEffect, useRef, useState } from 'react'
import { BrowserMultiFormatReader } from '@zxing/library'
import { ScanLine, Camera, CameraOff, Search } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { compactVnd } from '@/lib/crm'
import { SERIAL_STATUS_LABEL, SERIAL_STATUS_TONE } from '@/lib/wms'
import type { CatalogPart, SerialNumber } from '@/lib/types'
import { Card, PageHeader, Button, Tag } from '@/components/ui'

interface LookupResult { code: string; parts: CatalogPart[]; serials: SerialNumber[] }

export function ScanPage() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const readerRef = useRef<BrowserMultiFormatReader | null>(null)
  const [scanning, setScanning] = useState(false)
  const [manual, setManual] = useState('')
  const [result, setResult] = useState<LookupResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [camError, setCamError] = useState('')

  const stop = () => {
    readerRef.current?.reset()
    setScanning(false)
  }

  useEffect(() => () => { readerRef.current?.reset() }, [])

  const lookup = async (code: string) => {
    const c = code.trim()
    if (!c) return
    setBusy(true)
    try {
      const [parts, serials] = await Promise.all([
        api.get<{ results: CatalogPart[] }>('/catalog/parts/', { params: { search: c } }),
        api.get<{ results: SerialNumber[] }>('/wms/serials/', { params: { search: c } }),
      ])
      setResult({ code: c, parts: parts.data.results.slice(0, 5), serials: serials.data.results.slice(0, 5) })
    } catch (e) {
      setResult({ code: c, parts: [], serials: [] })
      apiError(e)
    } finally {
      setBusy(false)
    }
  }

  const start = async () => {
    setCamError('')
    setResult(null)
    const reader = new BrowserMultiFormatReader()
    readerRef.current = reader
    setScanning(true)
    try {
      await reader.decodeFromVideoDevice(null, videoRef.current!, (res) => {
        if (res) {
          const text = res.getText()
          stop()
          setManual(text)
          lookup(text)
        }
      })
    } catch (e) {
      setCamError(e instanceof Error ? e.message : 'Không mở được camera.')
      setScanning(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <PageHeader icon={<ScanLine size={20} className="text-flame" />} title="Quét mã"
        subtitle="Quét barcode/QR phụ tùng hoặc serial súng hàn" />

      <Card className="mb-4">
        <div className="aspect-video bg-ink rounded-lg overflow-hidden mb-3 grid place-items-center relative">
          <video ref={videoRef} className={`w-full h-full object-cover ${scanning ? '' : 'hidden'}`} />
          {!scanning && <div className="text-txt-2 text-sm flex flex-col items-center gap-2">
            <Camera size={28} /> Camera tắt
          </div>}
          {scanning && <div className="absolute inset-x-8 top-1/2 h-0.5 bg-flame/70 animate-pulse" />}
        </div>
        {camError && <p className="text-danger text-xs mb-2">{camError}</p>}
        <div className="flex gap-2">
          {!scanning
            ? <Button onClick={start}><Camera size={15} /> Bắt đầu quét</Button>
            : <Button variant="danger" onClick={stop}><CameraOff size={15} /> Dừng</Button>}
        </div>
        <div className="flex gap-2 mt-3 pt-3 border-t border-line">
          <input value={manual} onChange={(e) => setManual(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') lookup(manual) }}
            placeholder="Hoặc nhập mã tay…"
            className="flex-1 bg-ink-3 border border-line rounded-md px-3 py-2 text-sm focus:border-flame focus:outline-none" />
          <Button variant="ghost" onClick={() => lookup(manual)} disabled={busy}><Search size={15} /> Tra</Button>
        </div>
      </Card>

      {result && (
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
