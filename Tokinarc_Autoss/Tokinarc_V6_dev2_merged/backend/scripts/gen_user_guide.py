"""
Sinh HƯỚNG DẪN SỬ DỤNG (Word .docx) cho hệ thống Tokinarc CRM/WMS.
Chạy: python scripts/gen_user_guide.py [output.docx]
"""
from __future__ import annotations

import sys

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

FLAME = RGBColor(0xE2, 0x5A, 0x1C)


def main(out: str):
    d = Document()
    base = d.styles['Normal']
    base.font.name = 'Calibri'
    base.font.size = Pt(11)

    def h(text, level=1):
        p = d.add_heading(text, level=level)
        for r in p.runs:
            r.font.color.rgb = FLAME if level <= 1 else RGBColor(0x33, 0x33, 0x33)
        return p

    def para(text, bold=False):
        p = d.add_paragraph()
        r = p.add_run(text); r.bold = bold
        return p

    def bullet(text):
        d.add_paragraph(text, style='List Bullet')

    def steps(items):
        for it in items:
            d.add_paragraph(it, style='List Number')

    def table(headers, rows):
        t = d.add_table(rows=1, cols=len(headers))
        t.style = 'Light Grid Accent 1'
        for i, hd in enumerate(headers):
            c = t.rows[0].cells[i]; c.text = hd
            for r in c.paragraphs[0].runs: r.bold = True
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = str(v)
        d.add_paragraph()

    # ── Bìa ──
    title = d.add_paragraph(); title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run('HƯỚNG DẪN SỬ DỤNG\nHỆ THỐNG TOKINARC CRM · WMS')
    r.bold = True; r.font.size = Pt(22); r.font.color.rgb = FLAME
    sub = d.add_paragraph(); sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run('Quản lý khách hàng · Bán hàng · Kho vận · Trợ lý nội bộ').italic = True
    d.add_paragraph()

    # ── 1. Giới thiệu ──
    h('1. Giới thiệu', 1)
    para('Hệ thống gồm 3 phân hệ chính, dùng chung 1 đăng nhập:')
    bullet('CRM — Quản lý khách hàng, lead, cơ hội, báo giá, hợp đồng, đơn hàng, công nợ, dịch vụ.')
    bullet('WMS — Quản lý kho: tồn kho, nhập/xuất kho, serial, quét mã, kiểm kê.')
    bullet('CEO — Bảng điều hành & báo cáo tổng hợp (chỉ quản lý/CEO/admin).')
    para('Ngoài ra có Trợ lý nội bộ (thanh chat đáy mọi trang) giúp làm nhanh nghiệp vụ bằng câu lệnh.')

    # ── 2. Đăng nhập & phân quyền ──
    h('2. Đăng nhập & phân quyền', 1)
    steps(['Mở trình duyệt, vào địa chỉ hệ thống (vd http://localhost:5174).',
           'Nhập Tên đăng nhập và Mật khẩu → bấm Đăng nhập.',
           'Tùy vai trò (role), bạn sẽ thấy các phân hệ tương ứng.'])
    h('Tài khoản mẫu (môi trường demo)', 2)
    table(['Tài khoản', 'Mật khẩu', 'Vai trò'],
          [['admin', 'admin12345', 'Toàn quyền'],
           ['ceo1', 'tokinarc123', 'CEO — xem mọi thứ'],
           ['quanly1', 'tokinarc123', 'Quản lý (manager)'],
           ['sale1', 'tokinarc123', 'Nhân viên kinh doanh'],
           ['kho1', 'tokinarc123', 'Nhân viên kho'],
           ['kysu1', 'tokinarc123', 'Kỹ sư dịch vụ']])
    h('Ai làm được gì', 2)
    table(['Chức năng', 'Sale', 'Kho', 'Dịch vụ', 'Manager', 'CEO/Admin'],
          [['Khách hàng, Lead, Cơ hội, Báo giá', '✓ (của mình)', '–', '–', '✓ (tất cả)', '✓'],
           ['Duyệt báo giá cấp 1 / Ký đơn / Thu tiền', '–', '–', '–', '✓', '✓'],
           ['Duyệt báo giá cấp 2 (vượt ngưỡng)', '–', '–', '–', '–', '✓'],
           ['Ticket dịch vụ', '✓', '–', '✓', '✓', '✓'],
           ['Kho: nhập/xuất/kiểm kê/quét', '–', '✓', '–', '✓', '✓'],
           ['Bảng điều hành CEO & báo cáo', '–', '–', '–', '✓', '✓']])

    # ── 3. CRM ──
    h('3. Phân hệ CRM', 1)
    h('3.1. Khách hàng', 2)
    bullet('Vào menu Khách hàng để xem danh sách (sale chỉ thấy KH của mình).')
    bullet('Bấm Thêm KH để tạo mới; bấm vào 1 KH để xem hồ sơ 360 (KPI, liên hệ, cơ hội, báo giá, lịch sử làm việc).')
    bullet('Nút Import (quản lý+): tải dữ liệu khách hàng cũ từ Excel/CSV — xem mục 3.8.')
    h('3.2. Lead → Cơ hội', 2)
    steps(['Tạo Lead ở menu Leads; khi đủ điều kiện bấm "Chuyển KH" để tạo Khách hàng.',
           'Tạo Cơ hội (Opportunity), cập nhật giai đoạn (stage) và xác suất.',
           'Pipeline/Forecast hiển thị dự báo doanh thu có trọng số.'])
    h('3.3. Báo giá & DUYỆT 2 CẤP', 2)
    para('Quy trình báo giá:', bold=True)
    steps(['Sale tạo Báo giá (chọn KH + dòng hàng); hệ thống tự tính tổng tiền.',
           'Quản lý bấm "Duyệt" (cấp 1).',
           'Nếu giá trị < ngưỡng (mặc định 100 triệu) → "Đã duyệt" ngay.',
           'Nếu ≥ ngưỡng → chuyển "Chờ CEO duyệt"; CEO bấm "Duyệt cấp 2".',
           'Báo giá đã duyệt: bấm "Tạo đơn" (sinh đơn bán) hoặc "Tạo HĐ".'])
    bullet('Từ chối: quản lý bấm "Từ chối" và nhập lý do.')
    bullet('Chống tự duyệt: người tạo không tự duyệt báo giá của mình (trừ admin).')
    h('3.4. Hợp đồng – Đơn hàng – Công nợ', 2)
    bullet('Hợp đồng: soạn từ báo giá đã duyệt hoặc tạo trực tiếp; trạng thái nháp → hiệu lực → hết hạn.')
    bullet('Đơn bán: Ký (active) → Giao (shipping). Khi Giao, hệ thống tự tạo phiếu xuất kho WMS.')
    bullet('Công nợ: ghi nhận thanh toán làm giảm công nợ; xem phân tích tuổi nợ ở menu Công nợ.')
    h('3.5. Viếng thăm & Hoạt động (có ghi âm + recap)', 2)
    para('Sau khi gặp/gọi khách:', bold=True)
    steps(['Vào Visit (gặp trực tiếp) hoặc Hoạt động (gọi/Zalo/email).',
           'Chọn khách hàng, nhập nội dung.',
           'Tải "File ghi âm" (audio) + "File recap" (Word/PDF) nếu có.',
           'Nhập "Recap (văn bản)" tóm tắt buổi làm việc → Lưu.'])
    h('3.6. Lịch sử làm việc với khách hàng', 2)
    bullet('Mở hồ sơ khách (Customer 360) → mục "Lịch sử làm việc": dòng thời gian gộp Viếng thăm, Hoạt động, Báo giá, Đơn, Ticket; có nút nghe ghi âm / tải file recap.')
    h('3.7. Dịch vụ (Ticket) & Bảo hành', 2)
    bullet('Tạo Service Ticket cho yêu cầu hỗ trợ/bảo hành; có thể gắn số serial sản phẩm lỗi.')
    bullet('Tra cứu lịch sử 1 serial (đã bán cho ai, còn bảo hành không, ticket liên quan).')
    h('3.8. Import dữ liệu cũ (quản lý+)', 2)
    steps(['Ở trang Khách hàng / Leads / Hợp đồng / Công nợ, bấm Import.',
           'Bấm "Tải file mẫu (Excel)", điền dữ liệu cũ theo đúng cột.',
           'Chọn file → bấm "Xem trước" để kiểm tra (sẽ tạo / bỏ qua trùng / lỗi từng dòng).',
           'Bấm "Import" để ghi vào hệ thống. Bản ghi trùng mã sẽ được bỏ qua.'])

    # ── 4. WMS ──
    h('4. Phân hệ WMS (Kho)', 1)
    bullet('Tồn kho: xem tồn theo kho/ô; lọc "Sắp hết hàng".')
    bullet('Serial: theo dõi từng súng hàn theo serial + bảo hành.')
    h('4.1. Nhập kho', 2)
    steps(['Tạo đơn nhập (ASN → Nhập kho).',
           'Cách 1: bấm "Xác nhận nhận" để cộng tồn toàn bộ.',
           'Cách 2 (quét): bấm "Quét" → quét/nhập từng mã + số lượng → đủ thì "Xác nhận nhận".'])
    h('4.2. Xuất kho', 2)
    steps(['Tạo đơn xuất (hoặc tự sinh khi Giao đơn bán).',
           'Xem "Pick-list" để biết lấy hàng ở ô nào (theo FIFO/FEFO).',
           'Quét: bấm "Quét" → quét mã + ô + số lượng (trừ tồn) → đủ thì "Giao".'])
    h('4.3. Quét mã (điện thoại)', 2)
    para('Menu WMS → Quét mã, chọn 1 trong 4 chế độ:', bold=True)
    table(['Chế độ', 'Tác dụng'],
          [['Tra cứu', 'Quét → xem phụ tùng/serial'],
           ['Nhập kho', 'Quét mã + ô + SL → cộng tồn'],
           ['Xuất kho', 'Quét mã + ô + SL → trừ tồn'],
           ['Kiểm kê', 'Quét mã + ô + số đếm → đặt lại tồn']])
    bullet('Bấm "Bắt đầu quét" để bật camera; chọn "Đang quét vào: Mã hàng / Ô" để điền đúng ô.')
    h('4.4. Phiên kiểm kê', 2)
    steps(['Menu WMS → Kiểm kê → "Phiên mới".',
           'Quét từng mặt hàng: nhập Mã hàng + Mã ô + Số đếm thực tế.',
           'Xem bảng chênh lệch (Hệ thống vs Đếm).',
           'Bấm "Áp dụng" để điều chỉnh tồn theo số đếm (có ghi vết).'])

    # ── 5. CEO ──
    h('5. Phân hệ CEO (quản lý/CEO/admin)', 1)
    bullet('Bảng điều hành: doanh thu, công nợ, tồn kho, pipeline.')
    bullet('AI Summary — Tóm tắt điều hành: tổng hợp số liệu thật mọi phòng ban; bấm "Tải Excel" để xuất báo cáo.')
    bullet('Đánh giá kế hoạch (pipeline forecast), doanh thu, công nợ, giá trị tồn kho.')

    # ── 6. Trợ lý nội bộ ──
    h('6. Trợ lý nội bộ (thanh chat đáy trang)', 1)
    para('Gõ câu lệnh tiếng Việt; trợ lý làm theo đúng quyền của bạn:')
    table(['Bạn gõ', 'Trợ lý làm', 'Vai trò'],
          [['"làm báo giá cho Công ty ABC: 5 x 001002"', 'Tạo báo giá nháp', 'Sale+'],
           ['"soạn hợp đồng từ báo giá BG-0007"', 'Tạo hợp đồng nháp', 'Sale+'],
           ['"đơn của Công ty ABC"', 'Liệt kê đơn + công nợ', 'Sale+'],
           ['"tồn 001002"', 'Tra tồn theo ô', 'Mọi nhân viên'],
           ['"tra cứu phụ tùng 001002"', 'Spec + giá + súng tương thích', 'Mọi nhân viên'],
           ['"nhập kho 100 x 001002"', 'Lập phiếu nhập nháp', 'Kho, CEO, Admin'],
           ['"xuất kho 20 x 001002"', 'Lập phiếu xuất nháp', 'Kho, CEO, Admin'],
           ['"báo cáo điều hành"', 'Tóm tắt toàn công ty', 'Manager/CEO+'],
           ['"đánh giá kế hoạch pipeline"', 'Dự báo doanh thu', 'Manager/CEO+']])
    bullet('Khách hàng không dùng được trợ lý nội bộ; mỗi vai trò chỉ làm trong quyền của mình.')
    bullet('Hành động ghi (báo giá/hợp đồng/phiếu kho) tạo BẢN NHÁP; vào màn tương ứng để gửi/duyệt/xác nhận.')

    # ── 7. Thông báo ──
    h('7. Thông báo', 1)
    bullet('Biểu tượng chuông 🔔 ở góc trên hiển thị số thông báo chưa đọc.')
    bullet('Báo khi: báo giá chờ CEO duyệt, báo giá được duyệt/từ chối.')
    bullet('Bấm 1 thông báo để tới màn liên quan + đánh dấu đã đọc; "Đọc hết" để xóa badge.')

    # ── 8. Câu hỏi thường gặp ──
    h('8. Câu hỏi thường gặp', 1)
    para('Không thấy menu WMS?', bold=True)
    para('Chỉ Nhân viên kho / Manager / CEO / Admin mới thấy phân hệ WMS.')
    para('Không duyệt được báo giá?', bold=True)
    para('Chỉ Manager/CEO/Admin được duyệt; người tạo không tự duyệt báo giá của mình.')
    para('Quét không mở được camera?', bold=True)
    para('Dùng ô "nhập tay" thay thế; hoặc cấp quyền camera cho trình duyệt (cần HTTPS trên điện thoại).')

    d.save(out)
    print(f'Saved: {out}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'HUONG_DAN_SU_DUNG_TOKINARC.docx')
