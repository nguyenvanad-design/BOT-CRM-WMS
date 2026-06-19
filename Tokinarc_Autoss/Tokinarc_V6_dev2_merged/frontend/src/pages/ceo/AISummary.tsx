/**
 * Tokinarc frontend — src/pages/ceo/AISummary.tsx
 * Tóm tắt điều hành AI — tổng hợp hoạt động TẤT CẢ phòng ban (Sales/CRM/Dịch vụ/
 * Kho) từ data thật, do Gemini viết (fallback template). GET /analytics/assistant/summary/.
 */
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bot, RefreshCw, Sparkles } from 'lucide-react'
import { getExecSummary } from '@/lib/analytics'
import { apiError } from '@/lib/api'
import { PageHeader, Card, Button, Tag } from '@/components/ui'

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
          <Button variant="ghost" onClick={() => q.refetch()} disabled={q.isFetching}>
            <RefreshCw size={14} className={q.isFetching ? 'animate-spin' : ''} /> Làm mới
          </Button>
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
        Số liệu lấy trực tiếp từ DB (doanh thu, công nợ, pipeline, ticket, tồn kho…); AI chỉ
        diễn giải, không bịa số. Mỗi lần “Làm mới” gọi 1 lượt Gemini.
      </p>
    </div>
  )
}
