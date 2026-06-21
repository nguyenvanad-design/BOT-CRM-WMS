/**
 * Tokinarc frontend — src/lib/upload.ts
 * Tải file lên storage service (MinIO) qua POST /storage/upload/ (multipart, JWT).
 * Trả metadata FileObject để gắn vào Visit/Activity (ghi âm, recap).
 */
import { api } from '@/lib/api'

export interface UploadedFile {
  id: string
  filename: string
  download_url: string
}

export async function uploadFile(file: File, kind: string): Promise<UploadedFile> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('kind', kind)
  // axios tự set Content-Type multipart (kèm boundary) khi body là FormData.
  const res = await api.post('/storage/upload/', fd)
  return {
    id: String(res.data.id),
    filename: res.data.filename,
    download_url: res.data.download_url ?? `/api/v1/storage/files/${res.data.id}/download/`,
  }
}
