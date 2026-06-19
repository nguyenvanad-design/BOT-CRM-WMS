/**
 * Tokinarc frontend — src/pages/crm/AIHub.tsx
 * Trang giới thiệu các tính năng AI đang có (không phải placeholder):
 *  - Trợ lý CRM (thanh chat docked đáy mọi trang)
 *  - AI Summary điều hành (CEO, manager+)
 */
import { useNavigate } from 'react-router-dom'
import { Sparkles, MessageCircle, Bot, ArrowRight } from 'lucide-react'
import { useAuth, isManager } from '@/lib/auth/store'
import { Card, PageHeader } from '@/components/ui'

export function AIHubPage() {
  const nav = useNavigate()
  const role = useAuth((s) => s.user?.role)

  return (
    <div className="max-w-3xl">
      <PageHeader icon={<Sparkles size={20} className="text-flame" />} title="AI Gợi ý"
        subtitle="Các trợ lý AI có sẵn trong hệ thống" />

      <div className="grid sm:grid-cols-2 gap-3">
        <Card>
          <div className="flex items-center gap-2 mb-2">
            <MessageCircle size={18} className="text-flame" />
            <span className="font-semibold text-sm">Trợ lý CRM</span>
          </div>
          <p className="text-xs text-txt-2 leading-relaxed">
            Thanh chat ở <b className="text-txt">đáy mọi trang</b>. Hỏi nhanh số liệu thật:
            “Doanh thu hôm nay?”, “Dong Nai Steel còn nợ bao nhiêu?”, “Khách nào chưa mua 3 tháng?”.
            Số liệu lấy trực tiếp từ hệ thống, chỉ dành cho quản lý/admin.
          </p>
        </Card>

        <Card>
          <div className="flex items-center gap-2 mb-2">
            <Bot size={18} className="text-flame" />
            <span className="font-semibold text-sm">AI Summary điều hành</span>
          </div>
          <p className="text-xs text-txt-2 leading-relaxed mb-3">
            Tóm tắt tự động toàn bộ hoạt động các phòng ban (Sales/CRM/Dịch vụ/Kho) do AI viết
            từ số liệu thật — dành cho Ban Giám đốc.
          </p>
          {isManager(role) ? (
            <button onClick={() => nav('/ceo/ai-summary')}
              className="text-xs text-flame hover:underline flex items-center gap-1">
              Mở AI Summary <ArrowRight size={13} />
            </button>
          ) : (
            <span className="text-[11px] text-txt-2">Chỉ quản lý/admin xem được.</span>
          )}
        </Card>
      </div>

      <p className="text-[11px] text-txt-2 mt-3">
        Lưu ý: chatbot tư vấn sản phẩm cho <b className="text-txt">khách hàng</b> là dịch vụ riêng
        (tự chứa catalog), tách khỏi trợ lý nội bộ này.
      </p>
    </div>
  )
}
