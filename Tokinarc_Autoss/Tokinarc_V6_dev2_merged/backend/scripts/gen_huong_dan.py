"""
Sinh HƯỚNG DẪN SỬ DỤNG TOÀN BỘ (Word .docx):
  - Toàn bộ kịch bản luồng nghiệp vụ (đầu–cuối, ai chuyển cho ai).
  - Chi tiết TỪNG TRANG của CRM + WMS + CEO (nút/trường + thao tác).
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

    def flow(text):
        p = d.add_paragraph(); p.paragraph_format.space_after = Pt(0)
        r = p.add_run(text); r.bold = True; r.font.name = 'Consolas'
        r.font.size = Pt(9); r.font.color.rgb = BLUE

    def steps(items):
        for it in items:
            d.add_paragraph(it, style='List Number')

    def buttons(rows):
        t = d.add_table(rows=1, cols=2); t.style = 'Light Grid Accent 1'
        hc = t.rows[0].cells; hc[0].text = 'Nút / Trường'; hc[1].text = 'Tác dụng'
        for c in hc:
            for r in c.paragraphs[0].runs: r.bold = True
        for a, b in rows:
            cells = t.add_row().cells; cells[0].text = a; cells[1].text = b
            for r in cells[0].paragraphs[0].runs: r.bold = True
        d.add_paragraph()

    def table(headers, rows):
        t = d.add_table(rows=1, cols=len(headers)); t.style = 'Light Grid Accent 1'
        for i, hd in enumerate(headers):
            t.rows[0].cells[i].text = hd
            for r in t.rows[0].cells[i].paragraphs[0].runs: r.bold = True
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row): cells[i].text = str(v)
        d.add_paragraph()

    def scenario(title, steps_rows):
        hp = d.add_paragraph(); r = hp.add_run('▸ ' + title)
        r.bold = True; r.font.size = Pt(12); r.font.color.rgb = GREEN
        table(['#', 'Người làm', 'Thao tác', 'Kết quả / Trạng thái', 'Chuyển cho'], steps_rows)

    def page(title, purpose, btns, steps_list=None):
        h(title, 3); kv('Mục đích', purpose); buttons(btns)
        if steps_list:
            para('Các bước:'); steps(steps_list)

    # ════════ BÌA ════════
    t = d.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run('HƯỚNG DẪN SỬ DỤNG TOÀN BỘ\nTOKINARC CRM · WMS')
    r.bold = True; r.font.size = Pt(21); r.font.color.rgb = FLAME
    s = d.add_paragraph(); s.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s.add_run('Toàn bộ kịch bản nghiệp vụ + chi tiết từng trang').italic = True
    d.add_paragraph()
    para('Phần 1 (A–B): tổng quan & toàn bộ kịch bản luồng nghiệp vụ. '
         'Phần 2 (C–E): chi tiết từng trang CRM, WMS, CEO.')
    d.add_page_break()

    # ════════ A. TỔNG QUAN ════════
    h('A. Tổng quan, vai trò & đăng nhập', 1)
    table(['Vai trò', 'Phụ trách'],
          [['Sale', 'KH, lead, cơ hội, báo giá, hợp đồng, đơn bán'],
           ['Manager', 'Duyệt báo giá cấp 1, ký đơn, thu tiền, báo cáo'],
           ['CEO', 'Duyệt báo giá cấp 2, dashboard điều hành'],
           ['Nhân viên kho', 'Nhập/xuất/chuyển/quét/đếm (không sửa tồn)'],
           ['Quản lý kho', 'Điều chỉnh tồn, duyệt kiểm kê, FIFO/FEFO, KPI kho'],
           ['Dịch vụ', 'Ticket bảo hành/hỗ trợ'],
           ['Admin', 'Toàn quyền']])
    kv('Đăng nhập', 'Mở hệ thống → nhập tài khoản + mật khẩu → "Đăng nhập". '
       'Tùy vai trò sẽ thấy phân hệ CRM / WMS / CEO tương ứng.')

    # ════════ B. TOÀN BỘ KỊCH BẢN ════════
    h('B. Toàn bộ kịch bản nghiệp vụ', 1)

    h('B.1. Bán hàng đầy đủ (báo giá → giao hàng → thu tiền)', 2)
    flow("SALE báo giá ─► MANAGER duyệt c1 ─► (lớn) CEO duyệt c2 ─► SALE báo khách ─►")
    flow("   khách ĐỒNG Ý ─► SALE tạo HĐ + đơn ─► MANAGER ký ─► KHO xuất/giao ─► thu tiền")
    scenario('Chi tiết', [
        ['1', 'Sale', 'Tạo báo giá (KH + dòng hàng) → Lưu', 'BG: Nháp', 'Manager'],
        ['2', 'Manager', 'Bấm "Duyệt"', '<ngưỡng→Đã duyệt; ≥ngưỡng→Chờ CEO', 'CEO (nếu lớn)'],
        ['3', 'CEO', 'Bấm "Duyệt cấp 2"', 'BG: Đã duyệt', 'Sale'],
        ['4', 'Sale', 'Báo giá cho khách', 'Khách cân nhắc', 'Khách'],
        ['5', 'Khách', 'Đồng ý', '—', 'Sale'],
        ['6', 'Sale', 'Bấm "Tạo HĐ" và "Tạo đơn"', 'Sinh HĐ + Đơn (Nháp)', 'Manager'],
        ['7', 'Manager', 'Mở đơn → "Ký"', 'Đơn: Hiệu lực', 'Sale/Kho'],
        ['8', 'Manager/Sale', 'Bấm "Giao"', 'Đơn: Đang giao; tự sinh phiếu xuất WMS', 'NV kho'],
        ['9', 'NV kho', 'Phiếu xuất → "Quét soạn" (mã+ô+SL)', 'Trừ tồn; đủ → Đã soạn', 'NV kho'],
        ['10', 'NV kho', 'Bấm "Giao hàng"', 'Phiếu xuất: Đã giao; serial→đã bán', 'Manager'],
        ['11', 'Manager', 'Ghi thanh toán', 'Công nợ giảm', 'CEO'],
        ['12', 'CEO', 'Xem báo cáo', 'Dashboard cập nhật', '—'],
    ])

    h('B.2. Báo giá bị TỪ CHỐI → làm lại', 2)
    scenario('Chi tiết', [
        ['1', 'Sale', 'Tạo & gửi báo giá', 'BG: Nháp/Chờ duyệt', 'Manager'],
        ['2', 'Manager', 'Bấm "Từ chối" + nhập lý do', 'BG: Từ chối; Sale nhận thông báo 🔔', 'Sale'],
        ['3', 'Sale', 'Tạo báo giá mới (điều chỉnh giá/điều khoản)', 'BG mới: Nháp', 'Manager'],
    ])

    h('B.3. Nhập hàng vào kho', 2)
    scenario('Chi tiết', [
        ['1', 'NV kho', 'Tạo đơn nhập (kho + dòng + ô đích + lô/HSD)', 'Phiếu nhập: Nháp', 'NV kho'],
        ['2', 'NV kho', 'Bấm "Quét" → quét mã + SL', 'Cộng "đã nhận/cần nhận"', 'NV kho'],
        ['3', 'NV kho', 'Bấm "Xác nhận nhận"', 'Cộng tồn; tạo Lô (FEFO); ghi sổ kho', '—'],
    ])

    h('B.4. Chuyển kho / chuyển vị trí', 2)
    scenario('Chi tiết', [
        ['1', 'NV kho', 'Chọn ô nguồn + ô đích + SL → chuyển', 'Trừ ô nguồn, cộng ô đích; 2 dòng sổ kho', '—'],
    ])
    kv('Ghi chú', 'Đa kho: chuyển nội bộ hoặc liên kho đều ghi 2 movement (transfer).')

    h('B.5. Điều chỉnh tồn (sai lệch ngoài kiểm kê)', 2)
    scenario('Chi tiết', [
        ['1', 'NV kho', 'Phát hiện lệch → báo Quản lý kho', '—', 'Quản lý kho'],
        ['2', 'Quản lý kho', 'Inventory → "Điều chỉnh" (đặt tồn đúng + lý do)', 'Tồn cập nhật; ghi sổ kho (adjust)', '—'],
    ])
    kv('Phân quyền', 'Nhân viên kho KHÔNG được điều chỉnh tồn; chỉ Quản lý kho trở lên.')

    h('B.6. Kiểm kê định kỳ', 2)
    scenario('Chi tiết', [
        ['1', 'NV kho', 'Kiểm kê → "Phiên mới"', 'Phiên: Đang đếm', 'NV kho'],
        ['2', 'NV kho', 'Quét đếm từng ô (mã+ô+số đếm)', 'Lưu tồn HT vs số đếm', 'Quản lý kho'],
        ['3', 'Quản lý kho', 'Xem chênh lệch → "Áp dụng"', 'Tồn = số đếm; phiên: Đã áp dụng', '—'],
    ])

    h('B.7. Lead → Khách hàng → Cơ hội', 2)
    scenario('Chi tiết', [
        ['1', 'Sale', 'Tạo Lead', 'Lead: new', 'Sale'],
        ['2', 'Sale', 'Chăm sóc, cập nhật', 'contacted→qualified', 'Sale'],
        ['3', 'Sale', 'Bấm "Chuyển KH"', 'Tạo Khách hàng; Lead: converted', 'Sale'],
        ['4', 'Sale', 'Tạo Cơ hội cho KH', 'Opportunity: prospect…', 'Sale'],
    ])

    h('B.8. Dịch vụ / Bảo hành', 2)
    scenario('Chi tiết', [
        ['1', 'Dịch vụ', 'Tạo Ticket, gắn serial', 'Ticket: open', 'Dịch vụ'],
        ['2', 'Dịch vụ', 'Tra "Lịch sử serial" (đã bán/ bảo hành)', '—', 'Dịch vụ'],
        ['3', 'Dịch vụ', 'Xử lý', 'in_progress→resolved→closed', '—'],
    ])

    h('B.9. Thu tiền & theo dõi công nợ', 2)
    scenario('Chi tiết', [
        ['1', 'Manager', 'Ghi thanh toán cho đơn', 'paid_vnd tăng; nợ = tổng − đã thu', 'Kế toán'],
        ['2', 'Manager', 'Mở "Công nợ" xem tuổi nợ', 'Phân nhóm quá hạn', '—'],
    ])

    h('B.10. Import dữ liệu cũ (di trú)', 2)
    scenario('Chi tiết', [
        ['1', 'Quản lý', 'Tải file mẫu → điền Excel', '—', 'Quản lý'],
        ['2', 'Quản lý', 'Chọn file → "Xem trước"', 'Báo sẽ tạo/bỏ qua/lỗi (chưa ghi)', 'Quản lý'],
        ['3', 'Quản lý', 'Bấm "Import"', 'Ghi vào hệ thống (bỏ qua trùng)', '—'],
    ])

    h('B.11. Dùng Trợ lý nội bộ (làm nhanh)', 2)
    table(['Gõ', 'Tạo ra', 'Bước kế'],
          [['làm báo giá cho ABC: 5 x 001002', 'Báo giá nháp', 'Sale gửi → Manager duyệt'],
           ['nhập kho 100 x 001002', 'Phiếu nhập nháp', 'Kho xác nhận'],
           ['tồn 001002 / đơn của ABC', 'Tra cứu', '—'],
           ['báo cáo điều hành', 'Tóm tắt CEO', '—']])

    # ════════ C. CHI TIẾT TỪNG TRANG CRM ════════
    d.add_page_break()
    h('C. Chi tiết từng trang — CRM', 1)

    page('C.1. Dashboard (Tổng quan)', 'Bảng KPI nhanh: doanh số, cơ hội, công nợ, ticket.',
         [('Thẻ KPI', 'Chỉ xem nhanh, bấm có thể tới màn liên quan.')])
    page('C.2. Khách hàng', 'Danh sách KH (sale thấy của mình; manager+ thấy hết).',
         [('Ô tìm kiếm', 'Lọc tên/mã.'), ('Import (Quản lý+)', 'Nhập KH cũ Excel/CSV.'),
          ('Thêm KH', 'Form tạo KH.'), ('Bấm 1 dòng', 'Mở KH 360.'), ('Trước/Sau', 'Phân trang.')],
         ['Bấm "Thêm KH".', 'Nhập Mã (KH-…), Tên, Phân khúc, Vùng, MST.',
          '"Thêm người liên hệ" nếu cần.', 'Lưu.'])
    page('C.3. Khách hàng 360', 'Hồ sơ tổng hợp 1 KH.',
         [('← Quay lại', 'Về danh sách.'), ('Sửa', 'Sửa KH.'),
          ('Thẻ KPI', 'Đơn mở/công nợ/ticket/hoạt động gần nhất.'),
          ('Cơ hội / Báo giá', 'Của KH này.'),
          ('Lịch sử làm việc', 'Timeline; 🎧 ghi âm, 📄 recap.')])
    page('C.4. Người liên hệ (Contacts)', 'Danh bạ người liên hệ thuộc KH.',
         [('Tìm kiếm', 'Lọc tên/SĐT/công ty.'), ('Thêm liên hệ', 'Form thêm.'),
          ('★', 'Đánh dấu liên hệ chính.')])
    page('C.5. Leads', 'Khách tiềm năng.',
         [('Tạo Lead', 'Form lead.'), ('Chuyển KH', 'Tạo Khách hàng thật.'),
          ('Import (Quản lý+)', 'Nhập lead cũ.'), ('Bấm 1 dòng', 'Sửa lead.')])
    page('C.6. Opportunity (Cơ hội)', 'Quản lý thương vụ.',
         [('Tạo Opportunity', 'Form cơ hội.'), ('Bấm 1 dòng', 'Mở chi tiết + timeline.')])
    page('C.7. Opportunity Detail', 'Chi tiết 1 cơ hội + dòng thời gian tư vấn.',
         [('Đổi giai đoạn', 'Cập nhật stage.'), ('Sửa', 'Sửa cơ hội.'),
          ('Timeline', 'Visit + Activity gắn cơ hội.')])
    page('C.8. Pipeline', 'Bảng Kanban theo giai đoạn.',
         [('Cột giai đoạn', 'prospect→qualify→proposal→negotiate→won/lost.')])
    page('C.9. Forecast (CRM)', 'Dự báo doanh thu có trọng số từ cơ hội (phạm vi của bạn).',
         [('Biểu đồ/bảng', 'weighted = giá trị × xác suất theo giai đoạn.')])
    page('C.10. Báo giá (Quote)', 'Gửi giá + duyệt 2 cấp.',
         [('Tạo BG', 'Form: KH + dòng hàng; tổng tự tính.'),
          ('Bấm dòng (Nháp)', 'Sửa khi còn Nháp.'),
          ('Duyệt / Duyệt c1', 'Manager+ duyệt.'),
          ('Duyệt cấp 2 (CEO)', 'CEO/Admin duyệt báo giá lớn.'),
          ('Từ chối', 'Manager+ từ chối + lý do.'),
          ('Tạo đơn', 'BG đã duyệt → Đơn bán.'), ('Tạo HĐ', 'BG đã duyệt → Hợp đồng.')],
         ['Tạo BG, chọn KH, nhập dòng hàng, Tạo.', 'Manager "Duyệt".',
          'Nếu lớn: CEO "Duyệt cấp 2".', '"Tạo đơn"/"Tạo HĐ".'])
    page('C.11. Hợp đồng', 'Hợp đồng với KH.',
         [('Tạo HĐ', 'Form HĐ.'), ('Import (Quản lý+)', 'Nhập HĐ cũ (customer_code).'),
          ('Bấm 1 dòng', 'Sửa HĐ.'), ('Thẻ KPI', 'Hiệu lực/Chờ ký/Hết hạn/Tổng giá trị.')])
    page('C.12. Công nợ (Receivables)', 'Phải thu + tuổi nợ.',
         [('Import đơn cũ (Quản lý+)', 'Nhập đơn cũ.'), ('Phân tích tuổi nợ', 'Thanh tỷ lệ.'),
          ('Bấm 1 dòng', 'Mở KH liên quan.')])
    page('C.13. Visit Report (Viếng thăm)', 'Báo cáo gặp khách + ghi âm/recap.',
         [('Tạo visit', 'Form.'), ('File ghi âm/recap — Chọn file', 'Tải lên.'),
          ('Recap (văn bản)', 'Gõ tóm tắt.')])
    page('C.14. Hoạt động (Activity)', 'Nhật ký gọi/email/Zalo + ghi âm/recap.',
         [('Tạo hoạt động', 'Form.'), ('Loại', 'call/email/zalo/meeting.'),
          ('Ghi âm/recap', 'Như Visit.')])
    page('C.15. Service Ticket', 'Yêu cầu hỗ trợ/bảo hành.',
         [('Tạo Ticket', 'Form.'), ('Số serial', 'Gắn sản phẩm lỗi.'),
          ('Trạng thái', 'open→in_progress→resolved→closed.')])
    page('C.16. Bảo hành (Warranty)', 'Tra bảo hành theo serial súng hàn.',
         [('Tìm kiếm', 'Theo serial.'), ('Trạng thái', 'Còn hạn/sắp hết/hết hạn.')])
    page('C.17. Sản phẩm (Products)', 'Tra cứu catalog.',
         [('Tab Phụ tùng / Súng hàn', 'Đổi loại.'), ('Tìm kiếm', 'Theo mã/tên.'), ('Trước/Sau', 'Phân trang.')])
    page('C.18. AI Gợi ý (AIHub)', 'Giới thiệu các trợ lý AI.',
         [('Thẻ chức năng', 'Bấm để mở trợ lý tương ứng.')])

    # ════════ D. CHI TIẾT TỪNG TRANG WMS ════════
    d.add_page_break()
    h('D. Chi tiết từng trang — WMS', 1)
    page('D.1. Dashboard kho', 'KPI kho nhanh (tồn, sắp hết, đơn nhập/xuất).',
         [('Thẻ KPI', 'Chỉ xem.')])
    page('D.2. Tồn kho (Inventory)', 'Xem tồn theo ô + điều chỉnh (Quản lý kho).',
         [('Tìm kiếm', 'Theo tên/mã/ô.'), ('Lọc kho', '?warehouse khi đa kho.'),
          ('Điều chỉnh (Quản lý kho)', 'Đặt lại tồn 1 ô + lý do.'),
          ('Chuyển kho', 'Chuyển SL giữa 2 ô.')])
    page('D.3. Sắp hết hàng', 'Lọc mặt hàng tồn ≤ mức tối thiểu.',
         [('Danh sách', 'Ưu tiên bổ sung.')])
    page('D.4. Serial', 'Theo dõi từng súng hàn.',
         [('Tìm kiếm', 'Theo serial.'), ('Lịch sử serial', 'Đã bán cho ai, ticket, bảo hành.')])
    page('D.5. Lô hàng (Lots, FEFO)', 'Lô + hạn dùng.',
         [('Sắp hết hạn (≤30 ngày)', 'Lọc lô gần hết hạn (đỏ/vàng).')])
    page('D.6. Lịch sử kho (Movements)', 'Sổ cái mọi biến động tồn (chỉ xem).',
         [('Bộ lọc', 'Theo kho/part/thời gian.')])
    page('D.7. ASN (báo hàng về)', 'Khai báo hàng nhà cung cấp sắp về.',
         [('Tạo ASN', 'Form (NCC, ETA).'), ('Đã về (arrive)', 'Tạo phiếu nhập từ ASN.')])
    page('D.8. Nhập kho (Inbound)', 'Nhận hàng → cộng tồn.',
         [('Tạo đơn nhập', 'Kho + dòng + ô đích + lô/HSD.'),
          ('Quét', 'Cửa sổ quét nhận theo phiếu.'), ('Xác nhận', 'Cộng tồn.')],
         ['Tạo đơn nhập.', '"Quét" → quét mã + SL từng dòng.', '"Xác nhận nhận" khi đủ.'])
    page('D.9. Xuất kho (Outbound)', 'Soạn & giao → trừ tồn.',
         [('Tạo đơn xuất', 'Hoặc auto khi Giao đơn bán.'),
          ('Pick-list', 'Gợi ý ô lấy (FIFO/FEFO).'),
          ('Quét', 'Quét soạn (mã+ô+SL) → trừ tồn.'), ('Giao', 'Xác nhận giao.')])
    page('D.10. Kho & vị trí (Warehouses)', 'Danh sách kho / zone / ô.',
         [('Thẻ kho', 'Số vị trí (bin) mỗi kho.'), ('Mặc định', 'Kho auto khi 1 kho.')])
    page('D.11. Bản đồ kho (Map)', 'Sơ đồ trực quan các ô theo zone/tầng.',
         [('Lọc Có hàng/Trống', 'Tô màu ô.'), ('Zone/tầng', 'Hiển thị SUNG/MIG/TIG…')])
    page('D.12. Quét mã (Scan)', 'Quét barcode điện thoại — 4 chế độ.',
         [('Tra cứu', 'Quét → xem.'), ('Nhập kho', 'Quét + ô + SL → +tồn.'),
          ('Xuất kho', 'Quét + ô + SL → −tồn.'),
          ('Kiểm kê (Quản lý kho)', 'Quét + ô + số đếm → đặt tồn.'),
          ('Bắt đầu/Dừng', 'Camera.'), ('Đang quét: Mã/Ô', 'Chọn trường nhận mã.')])
    page('D.13. Kiểm kê (Cycle Count)', 'Phiên kiểm kê → đối chiếu → áp dụng.',
         [('Phiên mới', 'Tạo phiên.'), ('Quét đếm', 'Mã+ô+số đếm.'),
          ('Bảng chênh lệch', 'HT vs đếm.'), ('Áp dụng (Quản lý kho)', 'Điều chỉnh tồn.')])
    page('D.14. KPI vận hành (Quản lý kho+)', 'Năng suất + chính xác kiểm kê + tồn/zone + NV.',
         [('Kỳ 7/30/90', 'Khoảng thời gian.'), ('Thẻ KPI', 'Nhập/Xuất/Chính xác/Sắp hết.'),
          ('Tồn theo zone', 'SKU + tồn.'), ('Hiệu suất NV', 'Thao tác/người.')])
    page('D.15. Báo cáo kho (Reports)', 'Biểu đồ tồn/biến động.',
         [('Biểu đồ', 'Theo thời gian/zone.')])

    # ════════ E. CHI TIẾT TỪNG TRANG CEO ════════
    d.add_page_break()
    h('E. Chi tiết từng trang — CEO (Manager/CEO/Admin)', 1)
    page('E.1. Bảng điều hành (Overview)', 'KPI tổng hợp công ty.',
         [('Thẻ KPI', 'Doanh thu, công nợ, tồn, pipeline.')])
    page('E.2. AI Summary', 'Tóm tắt điều hành do AI viết từ số liệu thật.',
         [('Làm mới', 'Tổng hợp lại.'), ('Tải Excel', 'Xuất báo cáo .xlsx.')])
    page('E.3. Doanh thu / Công nợ / Forecast / Tồn kho', 'Báo cáo chuyên đề điều hành.',
         [('Biểu đồ', 'Theo kỳ.'), ('Lọc', 'Thời gian/phân khúc.')])

    # ════════ F. CÔNG CỤ + PHÂN QUYỀN ════════
    h('F. Công cụ hỗ trợ & phân quyền', 1)
    kv('Trợ lý nội bộ', 'Chat đáy trang; gõ lệnh làm nhanh theo quyền (tạo bản nháp).')
    kv('Thông báo 🔔', 'Báo giá chờ CEO duyệt / được duyệt / bị từ chối.')
    table(['Chức năng', 'Sale', 'NV kho', 'QL kho', 'Manager', 'CEO/Admin'],
          [['Báo giá/HĐ', '✓', '–', '–', '✓', '✓'],
           ['Duyệt BG cấp 1 / cấp 2', '– / –', '– / –', '– / –', '✓ / –', '✓ / ✓'],
           ['Nhập/xuất/quét kho', '–', '✓', '✓', '✓', '✓'],
           ['Điều chỉnh tồn / duyệt kiểm kê', '–', '✗', '✓', '✓', '✓'],
           ['KPI vận hành kho', '–', '–', '✓', '✓', '✓'],
           ['Dashboard CEO', '–', '–', '–', '✓', '✓']])

    d.save(out)
    print(f'Saved: {out}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'HUONG_DAN_SU_DUNG.docx')
