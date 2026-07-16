/**
 * Tokinarc frontend — src/lib/scanResolve.ts
 * Phân giải mã QUÉT (barcode/QR) → giá trị item của form ("part:001002" / "torch:TK-308RR").
 * Thứ tự: khớp thẳng part_no/model_code trong options → tra catalog theo barcode/mã (API).
 */
import { api } from '@/lib/api'

interface Opt { value: string; label: string }
interface PartLite { tokin_part_no: string; barcode?: string }

export async function resolveScanToItem(code: string, options: Opt[]): Promise<string | null> {
  const c = code.trim()
  if (!c) return null
  // 1) QR in mã nội bộ → khớp thẳng option (part:PN hoặc torch:MODEL).
  const direct = options.find((o) => o.value === `part:${c}` || o.value === `torch:${c}`)
  if (direct) return direct.value
  // 2) Barcode trên tem (EAN/mã Tokin đã quét-gán) → hỏi catalog (search khớp cả cột barcode).
  try {
    const r = await api.get<{ results?: PartLite[] } | PartLite[]>('/catalog/parts/', { params: { search: c } })
    const rows: PartLite[] = Array.isArray(r.data) ? r.data : (r.data.results ?? [])
    const exact = rows.find((p) => p.tokin_part_no === c || p.barcode === c)
    const hit = exact ?? (rows.length === 1 ? rows[0] : undefined)
    if (hit) return `part:${hit.tokin_part_no}`
  } catch { /* mạng lỗi → coi như không tìm thấy */ }
  return null
}
