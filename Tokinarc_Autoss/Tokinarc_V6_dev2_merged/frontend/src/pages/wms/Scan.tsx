/**
 * Tokinarc frontend — src/pages/wms/Scan.tsx
 * Quét barcode/QR bằng camera điện thoại (zxing-wasm — zxing-cpp/WASM) — 3 chế độ:
 *   - Tra cứu: quét → tìm phụ tùng (catalog) + serial (WMS).
 *   - Nhập kho: quét mã hàng + ô (bin) + SL → cộng tồn (POST scan-entry receive).
 *   - Kiểm kê: quét mã hàng + ô + số đếm → set tồn (POST scan-entry count).
 * Đọc đa định dạng (QR + Code128/EAN/UPC…), chạy cả Android & iOS. Cần HTTPS/localhost.
 * Có ô nhập tay khi không dùng được camera.
 */
import { useEffect, useRef, useState } from 'react'
import { readBarcodes, prepareZXingModule } from 'zxing-wasm/reader'
import wasmUrl from 'zxing-wasm/reader/zxing_reader.wasm?url'
import { ScanLine, Camera, CameraOff, Search, PackagePlus, PackageMinus, ClipboardCheck } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { compactVnd } from '@/lib/crm'
import { SERIAL_STATUS_LABEL, SERIAL_STATUS_TONE } from '@/lib/wms'
import type { CatalogPart, SerialNumber } from '@/lib/types'
import { Card, PageHeader, Button, Tag } from '@/components/ui'
import { useAuth, isWmsControl } from '@/lib/auth/store'

// Nạp WASM từ bundle local (kho có thể offline — không phụ thuộc CDN).
prepareZXingModule({ overrides: { locateFile: (p, prefix) => (p.endsWith('.wasm') ? wasmUrl : prefix + p) } })

type Mode = 'lookup' | 'receive' | 'issue' | 'count'
type Target = 'code' | 'bin'
interface LookupResult { code: string; parts: CatalogPart[]; serials: SerialNumber[] }
interface EntryLog { text: string; ok: boolean }

const MODES: { key: Mode; label: string; icon: typeof Search }[] = [
  { key: 'lookup', label: 'Tra cứu', icon: Search },
  { key: 'receive', label: 'Nhập kho', icon: PackagePlus },
  { key: 'issue', label: 'Xuất kho', icon: PackageMinus },
  { key: 'count', label: 'Kiểm kê', icon: ClipboardCheck },
]

export function ScanPage() {
  const canControl = isWmsControl(useAuth((s) => s.user?.role))
  const visibleModes = MODES.filter((m) => m.key !== 'count' || canControl)
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const rafRef = useRef<number>(0)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [mode, setMode] = useState<Mode>('lookup')
  const [scanning, setScanning] = useState(false)
  const [camError, setCamError] = useState('')
  const [busy, setBusy] = useState(false)
  const [hit, setHit] = useState('')   // mã vừa quét được (hiện flash "✓ đã quét")

  // Tra cứu
  const [manual, setManual] = useState('')
  const [result, setResult] = useState<LookupResult | null>(null)
  // Nhập kho / Kiểm kê
  const [target, setTarget] = useState<Target>('code')
  const [code, setCode] = useState('')
  const [binCode, setBinCode] = useState('')
  const [qty, setQty] = useState('')
  const [log, setLog] = useState<EntryLog[]>([])

  // Camera chỉ chạy ở "secure context" (HTTPS hoặc localhost). Mở qua http://<IP> → bị chặn.
  const cameraReady = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

  const stop = () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = 0
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setScanning(false)
  }
  useEffect(() => () => stop(), [])   // dọn camera khi rời trang

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

  // Tiếng "bíp" ngắn khi quét trúng mã (phản hồi như máy quét thật).
  const beep = () => {
    try {
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new Ctx()
      const o = ctx.createOscillator(); const g = ctx.createGain()
      o.connect(g); g.connect(ctx.destination)
      o.frequency.value = 880; g.gain.value = 0.08
      o.start(); o.stop(ctx.currentTime + 0.12)
      setTimeout(() => ctx.close(), 200)
    } catch { /* trình duyệt chặn audio — bỏ qua */ }
  }

  // Nhận 1 mã quét/nhập theo chế độ + đích đang quét
  const onCode = (text: string) => {
    beep()
    setHit(text); setTimeout(() => setHit(''), 1300)   // flash "✓ đã quét"
    if (mode === 'lookup') { setManual(text); lookup(text); return }
    if (target === 'code') setCode(text); else setBinCode(text)
    toast.success(`Đã quét: ${text}`)
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
    if (!cameraReady) {
      setCamError('Không bật được camera vì trang đang chạy HTTP (không bảo mật). '
        + 'Camera chỉ hoạt động khi mở bằng https://… hoặc localhost. '
        + 'Tạm thời hãy NHẬP MÃ BẰNG TAY ở ô bên dưới, hoặc dùng máy quét USB.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } }, audio: false,
      })
      streamRef.current = stream
      const v = videoRef.current!
      v.srcObject = stream
      v.setAttribute('playsinline', 'true')   // iOS Safari: không bật fullscreen
      await v.play()
      setScanning(true)
      scanLoop()
    } catch (e) {
      setCamError(e instanceof Error ? e.message : 'Không mở được camera.')
      stop()
    }
  }

  // Vòng lặp: mỗi frame → vẽ vào canvas → readBarcodes(zxing-wasm) → có mã thì xử lý.
  const scanLoop = () => {
    const canvas = canvasRef.current ?? (canvasRef.current = document.createElement('canvas'))
    let reading = false
    const tick = async () => {
      const v = videoRef.current
      if (!v || v.readyState < 2 || !streamRef.current) { rafRef.current = requestAnimationFrame(tick); return }
      if (!reading) {
        reading = true
        try {
          canvas.width = v.videoWidth; canvas.height = v.videoHeight
          const ctx = canvas.getContext('2d', { willReadFrequently: true })!
          ctx.drawImage(v, 0, 0, canvas.width, canvas.height)
          const img = ctx.getImageData(0, 0, canvas.width, canvas.height)
          const results = await readBarcodes(img, { tryHarder: true, maxNumberOfSymbols: 1 })
          const text = results[0]?.text
          if (text) {
            onCode(text)
            if (mode === 'lookup') { stop(); return }
          }
        } catch { /* bỏ qua frame lỗi */ }
        reading = false
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
  }

  const entryMode = mode === 'receive' || mode === 'issue' || mode === 'count'

  return (
    <div className="max-w-2xl">
      <PageHeader icon={<ScanLine size={20} className="text-flame" />} title="Quét mã"
        subtitle="Quét bằng điện thoại: tra cứu, nhập kho, kiểm kê" />

      {/* Chọn chế độ */}
      <div className="flex gap-1.5 mb-4">
        {visibleModes.map((m) => {
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
          {!scanning && cameraReady && <div className="text-txt-2 text-sm flex flex-col items-center gap-2"><Camera size={28} /> Camera tắt</div>}
          {!scanning && !cameraReady && (
            <div className="text-txt-2 text-xs flex flex-col items-center gap-2 px-6 text-center">
              <CameraOff size={28} className="text-warn" />
              <span>Camera bị chặn vì trang không chạy <b>HTTPS</b>.<br />Hãy <b>nhập mã bằng tay</b> bên dưới hoặc mở app qua <b>https://…</b></span>
            </div>
          )}
          {scanning && (
            <>
              {/* Khung ngắm + vạch quét chạy */}
              <div className="absolute inset-0 pointer-events-none grid place-items-center">
                <div className="relative w-[72%] h-[58%] rounded-lg border-2 border-flame/50">
                  {/* 4 góc bracket */}
                  <span className="absolute -top-0.5 -left-0.5 w-5 h-5 border-t-4 border-l-4 border-flame rounded-tl" />
                  <span className="absolute -top-0.5 -right-0.5 w-5 h-5 border-t-4 border-r-4 border-flame rounded-tr" />
                  <span className="absolute -bottom-0.5 -left-0.5 w-5 h-5 border-b-4 border-l-4 border-flame rounded-bl" />
                  <span className="absolute -bottom-0.5 -right-0.5 w-5 h-5 border-b-4 border-r-4 border-flame rounded-br" />
                  {/* vạch quét chạy lên-xuống */}
                  <div className="absolute inset-x-1 h-0.5 bg-flame shadow-[0_0_8px_2px] shadow-flame/70 animate-scanline" />
                </div>
              </div>
              {/* Badge "đang quét" */}
              <div className="absolute top-2 left-1/2 -translate-x-1/2 flex items-center gap-1.5 text-[11px] bg-ink/75 text-flame px-2.5 py-1 rounded-full">
                <span className="w-2 h-2 rounded-full bg-flame animate-pulse" /> Đang quét… đưa mã vào khung
              </div>
            </>
          )}
          {/* Flash khi quét trúng mã */}
          {hit && (
            <div className="absolute inset-0 grid place-items-center bg-ok/25 pointer-events-none">
              <div className="bg-ok text-white text-sm font-semibold px-4 py-2 rounded-lg flex items-center gap-2 shadow-lg">
                ✓ Đã quét: <span className="font-mono">{hit}</span>
              </div>
            </div>
          )}
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
            <Field label="Mã hàng" value={code} onChange={setCode} placeholder="Quét/nhập mã phụ tùng hoặc súng hàn" />
            <Field label="Mã ô (bin)" value={binCode} onChange={setBinCode} placeholder="VD HCM-A-K01-T1-03" />
            <Field label={mode === 'receive' ? 'Số lượng nhập' : mode === 'issue' ? 'Số lượng xuất' : 'Số đếm thực tế'}
              value={qty} onChange={setQty} placeholder="0" type="number" />
            <Button onClick={submitEntry} disabled={busy}>
              {mode === 'receive' ? <><PackagePlus size={15} /> Nhập kho</>
                : mode === 'issue' ? <><PackageMinus size={15} /> Xuất kho</>
                : <><ClipboardCheck size={15} /> Cập nhật tồn</>}
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
