/**
 * Tokinarc frontend — src/components/CameraScanner.tsx
 * Khung quét barcode/QR bằng camera điện thoại (zxing-wasm). Tái dùng cho:
 *   - Trang Quét mã (lẻ) và modal Quét theo phiếu Nhập/Xuất.
 * Mỗi lần đọc trúng mã → gọi onScan(code) + bíp + flash. Camera cần HTTPS/localhost.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { readBarcodes, prepareZXingModule } from 'zxing-wasm/reader'
import wasmUrl from 'zxing-wasm/reader/zxing_reader.wasm?url'
import { Camera, CameraOff } from 'lucide-react'
import { Button } from '@/components/ui'

// Nạp WASM từ bundle local (kho có thể offline — không phụ thuộc CDN).
prepareZXingModule({ overrides: { locateFile: (p, prefix) => (p.endsWith('.wasm') ? wasmUrl : prefix + p) } })

export function CameraScanner({ onScan }: { onScan: (code: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const rafRef = useRef<number>(0)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const onScanRef = useRef(onScan); onScanRef.current = onScan
  const [scanning, setScanning] = useState(false)
  const [camError, setCamError] = useState('')
  const [hit, setHit] = useState('')   // mã vừa quét — flash "✓ đã quét"

  // Camera chỉ chạy ở "secure context" (HTTPS / localhost).
  const cameraReady = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

  const stop = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = 0
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setScanning(false)
  }, [])
  useEffect(() => () => stop(), [stop])   // dọn camera khi rời

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

  const scanLoop = () => {
    const canvas = canvasRef.current ?? (canvasRef.current = document.createElement('canvas'))
    let reading = false
    let lastText = ''; let lastAt = 0
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
          // Chống quét trùng liên tục: cùng mã trong 1.5s thì bỏ qua.
          if (text && !(text === lastText && Date.now() - lastAt < 1500)) {
            lastText = text; lastAt = Date.now()
            beep(); setHit(text); setTimeout(() => setHit(''), 1300)
            onScanRef.current(text)
          }
        } catch { /* bỏ qua frame lỗi */ }
        reading = false
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
  }

  const start = async () => {
    setCamError('')
    if (!cameraReady) {
      setCamError('Camera bị chặn vì trang chạy HTTP. Chỉ chạy khi mở https://… hoặc localhost — '
        + 'tạm thời nhập mã bằng tay hoặc dùng máy quét USB.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
      streamRef.current = stream
      const v = videoRef.current!
      v.srcObject = stream
      v.setAttribute('playsinline', 'true')
      await v.play()
      setScanning(true)
      scanLoop()
    } catch (e) {
      setCamError(e instanceof Error ? e.message : 'Không mở được camera.')
      stop()
    }
  }

  return (
    <div>
      <div className="aspect-video bg-ink rounded-lg overflow-hidden grid place-items-center relative">
        <video ref={videoRef} className={`w-full h-full object-cover ${scanning ? '' : 'hidden'}`} />
        {!scanning && cameraReady && (
          <button onClick={start} className="flex flex-col items-center gap-2 text-txt-2 hover:text-flame text-sm">
            <Camera size={28} /> Bật camera quét
          </button>
        )}
        {!scanning && !cameraReady && (
          <div className="text-txt-2 text-xs flex flex-col items-center gap-2 px-6 text-center">
            <CameraOff size={28} className="text-warn" />
            <span>Camera bị chặn (cần <b>HTTPS</b>). Nhập mã bằng tay bên dưới.</span>
          </div>
        )}
        {scanning && (
          <>
            <div className="absolute inset-0 pointer-events-none grid place-items-center">
              <div className="relative w-[72%] h-[58%] rounded-lg border-2 border-flame/50">
                <span className="absolute -top-0.5 -left-0.5 w-5 h-5 border-t-4 border-l-4 border-flame rounded-tl" />
                <span className="absolute -top-0.5 -right-0.5 w-5 h-5 border-t-4 border-r-4 border-flame rounded-tr" />
                <span className="absolute -bottom-0.5 -left-0.5 w-5 h-5 border-b-4 border-l-4 border-flame rounded-bl" />
                <span className="absolute -bottom-0.5 -right-0.5 w-5 h-5 border-b-4 border-r-4 border-flame rounded-br" />
                <div className="absolute inset-x-1 h-0.5 bg-flame shadow-[0_0_8px_2px] shadow-flame/70 animate-scanline" />
              </div>
            </div>
            <div className="absolute top-2 left-1/2 -translate-x-1/2 flex items-center gap-1.5 text-[11px] bg-ink/75 text-flame px-2.5 py-1 rounded-full">
              <span className="w-2 h-2 rounded-full bg-flame animate-pulse" /> Đang quét… đưa mã vào khung
            </div>
          </>
        )}
        {hit && (
          <div className="absolute inset-0 grid place-items-center bg-ok/25 pointer-events-none">
            <div className="bg-ok text-white text-sm font-semibold px-4 py-2 rounded-lg flex items-center gap-2 shadow-lg">
              ✓ {hit}
            </div>
          </div>
        )}
      </div>
      {camError && <p className="text-danger text-xs mt-1.5">{camError}</p>}
      {scanning && (
        <div className="mt-1.5 text-right">
          <Button variant="ghost" size="sm" onClick={stop}><CameraOff size={13} /> Dừng camera</Button>
        </div>
      )}
    </div>
  )
}
