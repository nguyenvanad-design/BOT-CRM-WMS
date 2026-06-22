"""
Sinh HƯỚNG DẪN SỬ DỤNG & LUỒNG NGHIỆP VỤ (Word .docx).
Giải thích từng tính năng CRM/WMS + kịch bản luồng đầu–cuối (ai làm gì, chuyển cho ai).
Chạy: python scripts/gen_huong_dan.py [output.docx]
"""
from __future__ import annotations

import sys

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

FLAME = RGBColor(0xE2, 0x5A, 0x1C)
BLUE = RGBColor(0x12, 0x4D, 0xB5)
GREEN = RGBColor(0x1E, 0x7E, 0x34)
GREY = RGBColor(0x33, 0x33, 0x33)


def main(out: str):
    d = Document()
    d.styles['Normal'].font.name = 'Calibri'
    d.styles['Normal'].font.size = Pt(10.5)

    def h(text, level=1):
        p = d.add_heading(text, level=level)
        for r in p.runs:
            r.font.color.rgb = FLAME if level <= 1 else GREY
        return p

    def para(text):
        d.add_paragraph(text)

    def kv(label, text):
        p = d.add_paragraph()
        r = p.add_run(label + ': '); r.bold = True; r.font.color.rgb = FLAME
        p.add_run(text)

    def bullet(text):
        d.add_paragraph(text, style='List Bullet')

    def flow(text):
        p = d.add_paragraph(); p.paragraph_format.space_after = Pt(0)
        r = p.add_run(text); r.bold = True; r.font.name = 'Consolas'
        r.font.size = Pt(9); r.font.color.rgb = BLUE

    def table(headers, rows, widths=None):
        t = d.add_table(rows=1, cols=len(headers)); t.style = 'Light Grid Accent 1'
        for i, hd in enumerate(headers):
            t.rows[0].cells[i].text = hd
            for r in t.rows[0].cells[i].paragraphs[0].runs: r.bold = True
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row): cells[i].text = str(v)
        d.add_paragraph()

    def scenario(title, steps):
        """steps = list (Bước, Người làm, Thao tác, Kết quả/Trạng thái, Chuyển cho)."""
        hp = d.add_paragraph(); r = hp.add_run('▸ ' + title)
        r.bold = True; r.font.size = Pt(12); r.font.color.rgb = GREEN
        table(['#', 'Người làm', 'Thao tác', 'Kết quả / Trạng thái', 'Chuyển cho'], steps)

    # ════════ BÌA ════════
    t = d.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run('HƯỚNG DẪN SỬ DỤNG & LUỒNG NGHIỆP VỤ\nTOKINARC CRM · WMS')
    r.bold = True; r.font.size = Pt(21); r.font.color.rgb = FLAME
    s = d.add_paragraph(); s.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s.add_run('Giải thích từng tính năng + kịch bản công việc từ đầu đến cuối').italic = True
    d.add_paragraph()
    para('Tài liệu gồm 2 phần: (1) Giải thích từng tính năng CRM/WMS; '
         '(2) Các LUỒNG NGHIỆP VỤ đầu–cuối — ai làm gì, hệ thống đổi trạng thái ra sao, '
         'rồi chuyển việc cho ai.')
    d.add_page_break()

    # ════════ A. TỔNG QUAN ════════
    h('A. Tổng quan & vai trò', 1)
    table(['Vai trò', 'Phụ trách chính'],
          [['Sale', 'Khách hàng, lead, cơ hội, báo giá, hợp đồng, đơn bán'],
           ['Manager', 'Duyệt báo giá cấp 1, ký đơn, thu tiền, xem báo cáo'],
           ['CEO', 'Duyệt báo giá cấp 2 (giá trị lớn), dashboard điều hành'],
           ['Nhân viên kho', 'Nhập/xuất/chuyển/quét/đếm (không sửa tồn)'],
           ['Quản lý kho', 'Điều chỉnh tồn, duyệt kiểm kê, FIFO/FEFO, KPI kho'],
           ['Dịch vụ', 'Ticket bảo hành/hỗ trợ'],
           ['Admin', 'Toàn quyền']])
    kv('Đăng nhập', 'Vào địa chỉ hệ thống → nhập tài khoản/mật khẩu → bấm "Đăng nhập".')

    # ════════ B. CRM — TỪNG TÍNH NĂNG ════════
    h('B. CRM — giải thích từng tính năng', 1)

    feats_crm = [
        ('Khách hàng', 'Lưu hồ sơ khách + 360 (KPI, liên hệ, cơ hội, báo giá, lịch sử làm việc).',
         'Thêm KH / Sửa / Import Excel / bấm vào KH để xem 360.'),
        ('Lead', 'Khách tiềm năng chưa chính thức; sàng lọc rồi "Chuyển KH".',
         'Tạo Lead → Chuyển KH (tạo Khách hàng thật).'),
        ('Cơ hội (Opportunity)', 'Theo dõi 1 thương vụ + xác suất; nuôi Pipeline/Forecast.',
         'Tạo Opportunity, đổi giai đoạn (prospect→…→won/lost).'),
        ('Báo giá (Quote)', 'Gửi giá cho khách; DUYỆT 2 CẤP theo giá trị.',
         'Tạo BG (chọn KH + dòng hàng); Duyệt cấp 1/2; Từ chối; Tạo đơn; Tạo HĐ.'),
        ('Hợp đồng', 'Văn bản cam kết; sinh từ báo giá đã duyệt hoặc tạo trực tiếp.',
         'Tạo HĐ / Import; nháp→chờ ký→hiệu lực→hết hạn.'),
        ('Đơn bán', 'Đơn giao + thu tiền; khi Giao tự sinh phiếu xuất kho.',
         'Ký → Giao → (thu tiền qua công nợ).'),
        ('Công nợ', 'Phải thu + phân tích tuổi nợ.', 'Xem; Import đơn cũ; ghi thanh toán → giảm nợ.'),
        ('Viếng thăm / Hoạt động', 'Ghi lại gặp/gọi + tải ghi âm + recap.',
         'Tạo Visit/Activity; đính file ghi âm + file recap + nhập recap chữ.'),
        ('Lịch sử làm việc', 'Dòng thời gian mọi tương tác của 1 khách.',
         'Trong hồ sơ KH 360; nghe ghi âm / tải recap.'),
        ('Ticket & Bảo hành', 'Yêu cầu hỗ trợ/bảo hành; gắn serial sản phẩm.',
         'Tạo Ticket (gắn serial); tra Bảo hành theo serial.'),
        ('Import dữ liệu cũ', 'Đưa KH/Lead/Hợp đồng/Đơn cũ vào hệ thống.',
         'Tải mẫu → điền Excel → Xem trước → Import.'),
    ]
    for name, purpose, how in feats_crm:
        h(name, 3); kv('Chức năng', purpose); kv('Thao tác', how)

    # ════════ C. WMS — TỪNG TÍNH NĂNG ════════
    h('C. WMS — giải thích từng tính năng', 1)
    feats_wms = [
        ('Tồn kho', 'Xem còn bao nhiêu, ở ô nào; lọc sắp hết hàng.', 'Menu Tồn kho / Sắp hết hàng.'),
        ('Cấu trúc kho', 'Kho > Zone (nhóm SP) > Tầng (loại con) > Ô (vị trí).', 'Kho & vị trí / Bản đồ kho.'),
        ('Nhập kho', 'Nhận hàng NCC → cộng tồn.', 'Tạo đơn nhập → Quét nhận / Xác nhận nhận.'),
        ('Xuất kho', 'Soạn & giao hàng → trừ tồn.', 'Tạo/auto từ đơn bán → Pick-list/Quét soạn → Giao.'),
        ('Quét mã', 'Quét barcode điện thoại: tra cứu / nhập / xuất / kiểm kê.', 'Menu Quét mã, chọn chế độ.'),
        ('Kiểm kê (phiên)', 'Đếm thực tế → đối chiếu → áp dụng điều chỉnh tồn.', 'Phiên mới → quét đếm → Áp dụng (Quản lý kho).'),
        ('Lô hàng (FEFO)', 'Theo dõi lô + hạn dùng; xuất lô hết hạn trước.', 'Menu Lô hàng; cảnh báo sắp hết hạn.'),
        ('Serial', 'Theo dõi từng súng hàn + bảo hành.', 'Menu Serial; lịch sử serial.'),
        ('KPI vận hành', 'Năng suất nhập/xuất, độ chính xác kiểm kê, tồn theo zone, hiệu suất NV.', 'Menu KPI vận hành (Quản lý kho+).'),
    ]
    for name, purpose, how in feats_wms:
        h(name, 3); kv('Chức năng', purpose); kv('Thao tác', how)

    # ════════ D. CÁC LUỒNG NGHIỆP VỤ (TRỌNG TÂM) ════════
    d.add_page_break()
    h('D. Các luồng nghiệp vụ đầu–cuối', 1)
    para('Phần quan trọng nhất: mô tả công việc chạy qua nhiều người như thế nào.')

    h('D.1. Luồng BÁN HÀNG đầy đủ (báo giá → giao hàng → thu tiền)', 2)
    flow("SALE tạo báo giá ─► MANAGER duyệt cấp 1 ─► (lớn) CEO duyệt cấp 2 ─►")
    flow("   SALE báo khách ─► khách ĐỒNG Ý ─► SALE tạo hợp đồng + đơn bán ─►")
    flow("   MANAGER ký đơn ─► KHO xuất hàng ─► giao khách ─► MANAGER thu tiền")
    scenario('Kịch bản chi tiết', [
        ['1', 'Sale', 'Tạo báo giá (chọn KH + dòng hàng), bấm Lưu', 'Báo giá: Nháp → gửi', 'Manager'],
        ['2', 'Manager', 'Mở Báo giá, bấm "Duyệt"', 'Nếu < ngưỡng → Đã duyệt; nếu ≥ ngưỡng → Chờ CEO', 'CEO (nếu lớn)'],
        ['3', 'CEO', 'Bấm "Duyệt cấp 2"', 'Báo giá: Đã duyệt; CEO nhận thông báo 🔔 ở bước 2', 'Sale'],
        ['4', 'Sale', 'Báo giá cho khách hàng (ngoài hệ thống)', 'Khách xem xét', 'Khách hàng'],
        ['5', 'Khách', 'Đồng ý mua', '—', 'Sale'],
        ['6', 'Sale', 'Bấm "Tạo HĐ" và/hoặc "Tạo đơn" trên báo giá đã duyệt', 'Sinh Hợp đồng + Đơn bán (Nháp)', 'Manager'],
        ['7', 'Manager', 'Mở đơn bán, bấm "Ký"', 'Đơn: Hiệu lực (active)', 'Kho'],
        ['8', 'Manager/Sale', 'Bấm "Giao" trên đơn', 'Đơn: Đang giao; TỰ SINH phiếu xuất WMS', 'Nhân viên kho'],
        ['9', 'NV kho', 'Mở phiếu xuất → "Quét soạn" (mã + ô + SL)', 'Trừ tồn từng ô; đủ → Đã soạn', 'NV kho'],
        ['10', 'NV kho', 'Bấm "Giao hàng"', 'Phiếu xuất: Đã giao; tồn đã trừ; serial→đã bán', 'Manager'],
        ['11', 'Manager', 'Ghi nhận thanh toán', 'Đã thu tăng → Công nợ giảm', 'Kế toán/CEO'],
        ['12', 'CEO', 'Xem báo cáo (doanh thu/công nợ tự cập nhật)', 'Dashboard phản ánh đơn vừa bán', '—'],
    ])
    kv('Lưu ý duyệt 2 cấp', 'Báo giá nhỏ (< ngưỡng, mặc định 100 triệu) chỉ cần Manager duyệt 1 lần. '
       'Báo giá lớn (≥ ngưỡng) thì sau Manager (cấp 1) phải có CEO duyệt (cấp 2) mới thành "Đã duyệt".')
    kv('Chống tự duyệt', 'Người tạo không tự duyệt báo giá của mình; người duyệt cấp 1 ≠ cấp 2 (trừ admin).')

    h('D.2. Luồng NHẬP HÀNG vào kho', 2)
    flow("NCC giao hàng ─► KHO tạo phiếu nhập ─► Quét nhận từng mã ─► Xác nhận ─► CỘNG TỒN")
    scenario('Kịch bản', [
        ['1', 'NV kho', 'Tạo đơn nhập (chọn kho + dòng hàng + ô đích + lô/hạn dùng nếu có)', 'Phiếu nhập: Nháp', 'NV kho'],
        ['2', 'NV kho', 'Bấm "Quét" → quét mã + nhập SL từng mặt hàng', 'Cộng dồn "đã nhận / cần nhận"', 'NV kho'],
        ['3', 'NV kho', 'Khi đủ, bấm "Xác nhận nhận"', 'CỘNG TỒN vào ô; tạo Lô (FEFO); ghi Lịch sử kho', '—'],
    ])

    h('D.3. Luồng KIỂM KÊ kho', 2)
    flow("NV kho tạo phiên + quét đếm ─► QUẢN LÝ KHO xem chênh lệch ─► Áp dụng (điều chỉnh tồn)")
    scenario('Kịch bản', [
        ['1', 'NV kho', 'WMS → Kiểm kê → "Phiên mới"', 'Phiên: Đang đếm', 'NV kho'],
        ['2', 'NV kho', 'Quét đếm từng ô (mã + ô + số đếm)', 'Lưu: tồn hệ thống vs số đếm', 'Quản lý kho'],
        ['3', 'Quản lý kho', 'Xem bảng chênh lệch (xanh dư / đỏ thiếu)', '—', 'Quản lý kho'],
        ['4', 'Quản lý kho', 'Bấm "Áp dụng"', 'Tồn = số đếm; ghi Lịch sử kho; phiên: Đã áp dụng', '—'],
    ])
    kv('Phân quyền', 'Nhân viên kho ĐẾM được nhưng KHÔNG duyệt; chỉ Quản lý kho trở lên bấm "Áp dụng".')

    h('D.4. Luồng LEAD → KHÁCH HÀNG', 2)
    scenario('Kịch bản', [
        ['1', 'Sale', 'Tạo Lead (tên/công ty/SĐT/nguồn)', 'Lead: new', 'Sale'],
        ['2', 'Sale', 'Liên hệ, cập nhật trạng thái', 'contacted → qualified', 'Sale'],
        ['3', 'Sale', 'Bấm "Chuyển KH"', 'Tạo Khách hàng thật; Lead: converted', 'Sale (tạo cơ hội)'],
    ])

    h('D.5. Luồng DỊCH VỤ / BẢO HÀNH', 2)
    scenario('Kịch bản', [
        ['1', 'Khách/Sale', 'Báo sản phẩm lỗi', '—', 'Dịch vụ'],
        ['2', 'Dịch vụ', 'Tạo Ticket, gắn số serial', 'Ticket: open', 'Dịch vụ'],
        ['3', 'Dịch vụ', 'Tra "Lịch sử serial" → biết đã bán cho ai, còn bảo hành?', '—', 'Dịch vụ'],
        ['4', 'Dịch vụ', 'Xử lý → cập nhật trạng thái', 'in_progress → resolved → closed', '—'],
    ])

    # ════════ E. TRỢ LÝ + THÔNG BÁO ════════
    h('E. Công cụ hỗ trợ', 1)
    kv('Trợ lý nội bộ (chat đáy trang)', 'Gõ lệnh để làm nhanh theo quyền: '
       '"làm báo giá cho ABC: 5 x 001002", "tồn 001002", "báo cáo điều hành". '
       'Hành động tạo BẢN NHÁP để người dùng xác nhận.')
    kv('Thông báo (chuông 🔔)', 'Báo khi báo giá chờ CEO duyệt / được duyệt / bị từ chối. '
       'Bấm để tới màn liên quan.')

    # ════════ F. PHÂN QUYỀN ════════
    h('F. Phân quyền tóm tắt', 1)
    table(['Chức năng', 'Sale', 'NV kho', 'QL kho', 'Manager', 'CEO/Admin'],
          [['Tạo/sửa báo giá, hợp đồng', '✓', '–', '–', '✓', '✓'],
           ['Duyệt báo giá cấp 1', '–', '–', '–', '✓', '✓'],
           ['Duyệt báo giá cấp 2', '–', '–', '–', '–', '✓'],
           ['Nhập/xuất/quét kho', '–', '✓', '✓', '✓', '✓'],
           ['Điều chỉnh tồn / duyệt kiểm kê', '–', '✗', '✓', '✓', '✓'],
           ['KPI vận hành kho', '–', '–', '✓', '✓', '✓'],
           ['Dashboard CEO / tài chính', '–', '–', '–', '✓', '✓']])

    d.save(out)
    print(f'Saved: {out}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'HUONG_DAN_SU_DUNG.docx')
