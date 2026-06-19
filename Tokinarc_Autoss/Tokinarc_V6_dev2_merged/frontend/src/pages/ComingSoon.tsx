/**
 * Tokinarc frontend — src/pages/ComingSoon.tsx
 * Trang giữ chỗ TRUNG THỰC cho mục có trong thiết kế (mockup) nhưng CHƯA có
 * model/endpoint backend. Không bịa dữ liệu — nêu rõ vì sao chưa hiển thị.
 */
import { Construction } from 'lucide-react'
import { PageHeader } from '@/components/ui'

export function ComingSoon({ title, reason }: { title: string; reason?: string }) {
  return (
    <div className="max-w-3xl">
      <PageHeader title={title} />
      <div className="border border-dashed border-line rounded-lg bg-ink-2 p-10 text-center">
        <Construction size={32} className="text-flame mx-auto mb-3" />
        <p className="text-sm font-medium">Tính năng đang phát triển</p>
        <p className="text-xs text-txt-2 mt-1.5 max-w-md mx-auto leading-relaxed">
          {reason ?? 'Màn hình này có trong thiết kế nhưng backend chưa có endpoint tương ứng. Sẽ nối API khi model sẵn sàng.'}
        </p>
      </div>
    </div>
  )
}
