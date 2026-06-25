/**
 * Tokinarc frontend — src/lib/download.ts
 * Tải file nhị phân (Excel…) qua axios (kèm JWT) rồi lưu xuống máy.
 */
import { api, apiError } from '@/lib/api'
import { toast } from 'sonner'

export async function downloadFile(url: string, filename: string) {
  try {
    const res = await api.get(url, { responseType: 'blob' })
    const href = URL.createObjectURL(res.data as Blob)
    const a = document.createElement('a')
    a.href = href
    a.download = filename
    a.click()
    URL.revokeObjectURL(href)
  } catch (e) {
    toast.error(apiError(e))
  }
}
