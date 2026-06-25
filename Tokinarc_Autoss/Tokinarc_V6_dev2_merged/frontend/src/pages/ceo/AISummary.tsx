/**
 * Tokinarc frontend — src/pages/ceo/AISummary.tsx
 * Tóm tắt điều hành AI — tổng hợp hoạt động TẤT CẢ phòng ban (Sales/CRM/Dịch vụ/
 * Kho) từ data thật, do Gemini viết (fallback template). GET /analytics/assistant/summary/.
 */
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bot, RefreshCw, Sparkles, Download } from 'lucide-react'
import { toast } from 'sonner'
import { getExecSummary } from '@/lib/analytics'
import { api, apiError } from '@/lib/api'
import { PageHeader, Card, Button, Tag } from '@/components/ui'

async function exportSummary() {
  try {
    const res = await api.get('/analytics/assistant/summary/export/', { responseType: 'blob' })
    const url = URL.createObjectURL(res.data as Blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'bao_cao_dieu_hanh.xlsx'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { toast.error(apiError(e)) }
}

export function CeoAISummaryPage() {
  const q = useQuery({
    queryKey: ['ceo', 'ai-summary'],
    queryFn: getExecSummary,
    staleTime: 5 * 60 * 1000,   // tránh gọi Gemini lặp khi điều hướng qua lại
  })

  return (
    <div className="max-w-3xl">
      <PageHeader
        icon={<Bot size={20} className="text-flame" />}
        title="AI Summary — Tóm tắt điều hành"
        subtitle="Tổng hợp hoạt động tất cả phòng ban từ số liệu thật"
        actions={
          <>
            <Button variant="ghost" onClick={exportSummary}><Download size={14} /> Tải Excel</Button>
            <Button variant="ghost" onClick={() => q.refetch()} disabled={q.isFetching}>
              <RefreshCw size={14} className={q.isFetching ? 'animate-spin' : ''} /> Làm mới
            </Button>
          </>
        }
      />

      <Card>
        {q.isLoading && (
          <div className="flex items-center gap-2 text-txt-2 text-sm py-10 justify-center">
            <Sparkles size={16} className="text-flame animate-pulse" /> AI đang tổng hợp số liệu các phòng ban…
          </div>
        )}
        {q.isError && <p className="text-danger text-sm py-6">Lỗi: {apiError(q.error)} (cần quyền quản lý/admin)</p>}
        {q.data && (
          <>
            <div className="flex items-center gap-2 mb-3 text-xs text-txt-2">
              {q.data.generated_by === 'ai'
                ? <Tag tone="purple">✨ AI viết (Gemini)</Tag>
                : <Tag tone="gray">Bản mẫu (LLM offline)</Tag>}
              <span>· cập nhật khi bấm “Làm mới”</span>
            </div>
            <div className="markdown text-sm leading-relaxed space-y-2">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  strong: ({ children }) => <strong className="text-txt font-semibold">{children}</strong>,
                  p: ({ children }) => <p className="text-txt-2">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc pl-5 space-y-1 text-txt-2">{children}</ul>,
                  li: ({ children }) => <li>{children}</li>,
                  h1: ({ children }) => <h3 className="text-flame font-semibold mt-3">{children}</h3>,
                  h2: ({ children }) => <h3 className="text-flame font-semibold mt-3">{children}</h3>,
                }}
              >
                {q.data.summary}
              </ReactMarkdown>
            </div>
          </>
        )}
      </Card>

      <p className="text-[11px] text-txt-2 mt-3">
        Tổng hợp từ DB: số liệu (doanh thu, công nợ, pipeline, ticket, tồn kho) <b>+ hoạt động 30 ngày</b>
        (recap cuộc gặp/gọi khách, đếm ghi âm, hoạt động kho nhập/xuất/kiểm kê). AI chỉ diễn giải,
        không bịa. Mỗi lần “Làm mới” gọi 1 lượt Gemini.
      </p>
    </div>
  )
}
