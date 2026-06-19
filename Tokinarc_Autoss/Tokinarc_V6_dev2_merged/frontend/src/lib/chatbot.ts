/**
 * Tokinarc frontend — src/lib/chatbot.ts
 * Gọi chatbot FastAPI (service riêng) qua proxy dev `/chatbot` → :8080.
 * Auth X-API-Key được Vite proxy chèn phía server (không nằm trong bundle).
 * Khác hẳn `api.ts` (Django/JWT) — chatbot tự chứa data, không đụng Postgres CRM.
 */
const CHATBOT_BASE = import.meta.env.VITE_CHATBOT_BASE ?? '/chatbot'

export interface ChatReply {
  text: string
  session_id: string | null
  success: boolean
}

export async function askChatbot(query: string, sessionId?: string | null): Promise<ChatReply> {
  const res = await fetch(`${CHATBOT_BASE}/api/v2/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, session_id: sessionId ?? null }),
  })
  if (!res.ok) {
    let detail = `Chatbot lỗi (HTTP ${res.status})`
    try {
      const d = await res.json()
      if (d?.detail) detail = d.detail
    } catch { /* giữ message mặc định */ }
    throw new Error(detail)
  }
  const d = await res.json()
  return {
    text: d.text ?? '(không có nội dung trả lời)',
    session_id: d.session_id ?? null,
    success: d.success ?? true,
  }
}
