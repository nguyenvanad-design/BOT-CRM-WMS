/**
 * Tokinarc frontend — src/components/TodayTasks.tsx
 * Ô "Việc hôm nay" — gom các TÍN HIỆU sẵn có thành danh sách việc cần làm.
 * Dùng chung cho Dashboard kho (kiểm kê/sắp hết/hàng về) và CRM (lead/báo giá/công nợ).
 * KHÔNG thêm dữ liệu mới — chỉ trình bày lại số liệu đang có.
 */
import { useNavigate } from 'react-router-dom'
import { ClipboardList, CheckCircle2, ChevronRight } from 'lucide-react'
import { Card, SectionTitle } from '@/components/ui'

export interface TodayTask {
  label: string
  count?: number          // số việc cần làm; bỏ trống = lời nhắc (luôn hiện)
  to?: string             // click → điều hướng tới trang xử lý
  tone?: 'danger' | 'warn' | 'flame' | 'ok'
  cta?: string            // gợi ý hành động (vd "Báo mua hàng")
}

const DOT: Record<NonNullable<TodayTask['tone']>, string> = {
  danger: 'bg-danger', warn: 'bg-warn', flame: 'bg-flame', ok: 'bg-ok',
}

export function TodayTasks({ items, loading }: { items: TodayTask[]; loading?: boolean }) {
  const nav = useNavigate()
  const todo = items.filter((i) => i.count === undefined || i.count > 0)   // còn việc / lời nhắc
  const done = items.filter((i) => i.count === 0)                          // đã xong

  return (
    <Card className="mb-4">
      <SectionTitle>
        <span className="flex items-center gap-1.5"><ClipboardList size={15} className="text-flame" /> Việc hôm nay</span>
      </SectionTitle>
      {loading ? (
        <p className="text-xs text-txt-2">Đang tải…</p>
      ) : (
        <div className="space-y-1">
          {todo.length === 0 && (
            <p className="text-sm text-ok flex items-center gap-1.5">
              <CheckCircle2 size={15} /> Hết việc tồn đọng hôm nay 🎉 — kiểm kê / sắp xếp / tìm khách tiếp.
            </p>
          )}
          {todo.map((i, k) => (
            <button key={k} onClick={() => i.to && nav(i.to)} disabled={!i.to}
              className="w-full flex items-center gap-2.5 text-left rounded-md px-2 py-1.5
                         hover:bg-ink-3/60 transition-colors disabled:cursor-default">
              <span className={`w-2 h-2 rounded-full shrink-0 ${DOT[i.tone ?? 'flame']}`} />
              <span className="text-sm flex-1">
                {i.label}{i.count !== undefined && <span className="font-semibold tabular-nums"> · {i.count}</span>}
              </span>
              {i.cta && <span className="text-xs text-flame whitespace-nowrap">{i.cta}</span>}
              {i.to && <ChevronRight size={14} className="text-txt-2 shrink-0" />}
            </button>
          ))}
          {done.map((i, k) => (
            <div key={`d${k}`} className="flex items-center gap-2.5 px-2 py-1 text-sm text-txt-2">
              <CheckCircle2 size={14} className="text-ok shrink-0" /> <span className="line-through">{i.label}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}
