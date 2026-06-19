/**
 * Tokinarc frontend — src/lib/assistant.ts
 * Trợ lý CRM NỘI BỘ — gọi endpoint Django (JWT, chỉ manager/admin):
 *   POST /api/v1/analytics/assistant/query/  →  { text }
 * Số liệu (doanh thu/công nợ/KH) lấy thật từ DB. KHÁC chatbot khách (catalog).
 */
import { api } from '@/lib/api'

export interface AssistantReply { text: string }

export async function askAssistant(query: string): Promise<AssistantReply> {
  const res = await api.post('/analytics/assistant/query/', { query })
  return { text: res.data.text ?? '(không có nội dung)' }
}
