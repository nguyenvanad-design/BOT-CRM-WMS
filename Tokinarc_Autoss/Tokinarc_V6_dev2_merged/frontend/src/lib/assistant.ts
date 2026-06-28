/**
 * Tokinarc frontend — src/lib/assistant.ts
 * Trợ lý CRM NỘI BỘ — gọi endpoint Django (JWT, chỉ manager/admin):
 *   POST /api/v1/analytics/assistant/query/  →  { text }
 * Số liệu (doanh thu/công nợ/KH) lấy thật từ DB. KHÁC chatbot khách (catalog).
 */
import { api } from '@/lib/api'

export interface AssistantReply { text: string }
export interface ChatTurn { role: 'user' | 'bot'; text: string }

/** Gửi câu hỏi (+ lịch sử hội thoại để bot hiểu ngữ cảnh, + tùy chọn file) cho trợ lý nội bộ. */
export async function askAssistant(query: string, file?: File | null, history?: ChatTurn[]): Promise<AssistantReply> {
  if (file) {
    const fd = new FormData()
    fd.append('query', query)
    fd.append('file', file)
    const res = await api.post('/analytics/assistant/query/', fd)
    return { text: res.data.text ?? '(không có nội dung)' }
  }
  const res = await api.post('/analytics/assistant/query/', { query, history: history ?? [] })
  return { text: res.data.text ?? '(không có nội dung)' }
}
