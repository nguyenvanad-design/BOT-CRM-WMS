"""
Sinh HƯỚNG DẪN LUỒNG NGHIỆP VỤ (ERP) — Word .docx.
Giải thích: mục đích từng tính năng, luồng trạng thái, bấm nút thì chuyển đi đâu,
ai xử lý tiếp, dữ liệu liên kết sang tính năng nào.
Chạy: python scripts/gen_user_guide.py [output.docx]
"""
from __future__ import annotations

import sys

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

FLAME = RGBColor(0xE2, 0x5A, 0x1C)
GREY = RGBColor(0x33, 0x33, 0x33)
BLUE = RGBColor(0x1C, 0x5A, 0xE2)


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
        """Dòng sơ đồ luồng (đậm, màu xanh, font đều)."""
        p = d.add_paragraph()
        r = p.add_run(text); r.bold = True; r.font.name = 'Consolas'
        r.font.size = Pt(9.5); r.font.color.rgb = BLUE

    def bullet(text):
        d.add_paragraph(text, style='List Bullet')

    def steps(items):
        for it in items:
            d.add_paragraph(it, style='List Number')

    def table(headers, rows):
        t = d.add_table(rows=1, cols=len(headers)); t.style = 'Light Grid Accent 1'
        for i, hd in enumerate(headers):
            t.rows[0].cells[i].text = hd
            for r in t.rows[0].cells[i].paragraphs[0].runs: r.bold = True
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row): cells[i].text = str(v)
        d.add_paragraph()

    # ════════ BÌA ════════
    t = d.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run('HƯỚNG DẪN LUỒNG NGHIỆP VỤ (ERP)\nTOKINARC CRM · WMS')
    r.bold = True; r.font.size = Pt(22); r.font.color.rgb = FLAME
    s = d.add_paragraph(); s.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s.add_run('Mục đích · Luồng trạng thái · Bấm nút thì đi đâu · Ai xử lý tiếp · Liên kết dữ liệu').italic = True
    d.add_paragraph()
    para('Tài liệu này KHÔNG chỉ liệt kê nút, mà giải thích DÒNG CHẢY công việc: '
         'mỗi tính năng dùng để làm gì, sau khi bấm nút thì hồ sơ chuyển sang trạng thái nào, '
         'ai là người xử lý bước kế tiếp, và dữ liệu nối sang phân hệ nào.')
    p = d.add_paragraph(); p.add_run('Ký hiệu luồng: ').bold = True
    p.add_run('A ──(nút/điều kiện)──► B  nghĩa là từ A bấm nút/đạt điều kiện sẽ sang B.')
    d.add_page_break()

    # ════════ 1. LUỒNG TỔNG THỂ ════════
    h('1. Luồng tổng thể toàn hệ thống (xương sống ERP)', 1)
    para('Toàn bộ nghiệp vụ nối thành một chuỗi từ khách hàng tiềm năng đến thu tiền và xuất kho:')
    flow('LEAD ─(Chuyển KH)─► KHÁCH HÀNG ─► CƠ HỘI ─► BÁO GIÁ ─(duyệt 2 cấp)─► ')
    flow('   ─(Tạo đơn)─► ĐƠN BÁN ─(Ký)─► ─(Giao)─► [tự sinh] PHIẾU XUẤT WMS ─► TRỪ TỒN')
    flow('   ─► THANH TOÁN ─► CÔNG NỢ ─► [tổng hợp] BÁO CÁO CEO')
    para('Song song, hàng vào kho theo luồng:')
    flow('ASN ─(Đã về)─► PHIẾU NHẬP ─(Quét/Xác nhận)─► CỘNG TỒN ─► (sẵn sàng bán)')
    para('Mọi thay đổi tồn đều ghi "Lịch sử kho" (sổ cái). Số liệu CRM + WMS đổ về CEO để báo cáo. '
         'Trợ lý nội bộ (chat) là lối tắt tạo nhanh các bước trên theo quyền.')
    h('1.1. Vai trò xử lý từng chặng', 2)
    table(['Chặng', 'Ai làm', 'Bước kế tiếp'],
          [['Lead → Khách hàng', 'Sale', 'Tạo cơ hội'],
           ['Cơ hội → Báo giá', 'Sale', 'Trình duyệt'],
           ['Duyệt báo giá cấp 1', 'Manager', 'Đủ lớn → CEO; nhỏ → tạo đơn'],
           ['Duyệt báo giá cấp 2', 'CEO/Admin', 'Tạo đơn'],
           ['Ký & Giao đơn bán', 'Manager/CEO (ký), Sale/Kho (giao)', 'Sinh phiếu xuất WMS'],
           ['Soạn & Giao hàng (kho)', 'Kho', 'Trừ tồn, ghi xuất kho'],
           ['Thu tiền', 'Manager/CEO', 'Giảm công nợ'],
           ['Nhập kho', 'Kho', 'Cộng tồn']])

    # ════════ 2. CRM — LUỒNG TỪNG TÍNH NĂNG ════════
    h('2. CRM — luồng từng tính năng', 1)

    h('2.1. Lead (khách tiềm năng)', 2)
    kv('Mục đích', 'Quản lý khách CHƯA thành khách hàng chính thức; sàng lọc trước khi đưa vào bán.')
    kv('Luồng trạng thái', '')
    flow('new ─► contacted ─► qualified ─(nút "Chuyển KH")─► [tạo KHÁCH HÀNG] = converted')
    flow('                                └────────────────► lost (thất bại)')
    kv('Bấm "Chuyển KH" thì gì xảy ra',
       'Hệ thống tạo một Khách hàng mới từ thông tin lead, đánh dấu lead = "converted", '
       'và từ đó bạn làm việc tiếp ở màn Khách hàng / Cơ hội.')
    kv('Nối sang', 'Khách hàng (mới) → Cơ hội → Báo giá.')

    h('2.2. Cơ hội (Opportunity)', 2)
    kv('Mục đích', 'Theo dõi một thương vụ đang đàm phán với khách + xác suất thắng.')
    kv('Luồng giai đoạn (kéo trên Pipeline hoặc đổi trong chi tiết)', '')
    flow('prospect ─► qualify ─► proposal ─► negotiate ─► won (thắng)')
    flow('                                            └─► lost (thua)')
    kv('Tự động chảy đi đâu',
       'Giá trị cơ hội × xác suất = "weighted" → nuôi màn Pipeline và Forecast (dự báo doanh thu). '
       'Khi đã chốt, tạo Báo giá cho khách.')

    h('2.3. Báo giá — LUỒNG DUYỆT 2 CẤP (trọng tâm)', 2)
    kv('Mục đích', 'Gửi giá cho khách; kiểm soát phê duyệt theo giá trị trước khi thành đơn/hợp đồng.')
    kv('Luồng đầy đủ', '')
    flow('Sale: (Tạo BG) ─► draft ─► sent')
    flow('Manager bấm "Duyệt" (CẤP 1):')
    flow('   • tổng < ngưỡng (mặc định 100 triệu) ──────────────► approved (Đã duyệt)')
    flow('   • tổng ≥ ngưỡng ─► pending_ceo (Chờ CEO duyệt)')
    flow('CEO/Admin bấm "Duyệt cấp 2" ───────────────────────► approved (Đã duyệt)')
    flow('Manager/CEO bấm "Từ chối" (nhập lý do) ─────────────► rejected')
    flow('approved ─(nút "Tạo đơn")─► ĐƠN BÁN     |     approved ─(nút "Tạo HĐ")─► HỢP ĐỒNG')
    kv('Giải thích "Duyệt"',
       'Bấm "Duyệt" là DUYỆT CẤP 1 do Manager thực hiện. Nếu báo giá nhỏ thì xong luôn. '
       'Nếu báo giá lớn (≥ ngưỡng) thì hệ thống KHÔNG duyệt ngay mà chuyển trạng thái '
       '"Chờ CEO duyệt"; lúc này CEO mới thấy nút "Duyệt cấp 2" để duyệt lần 2 → mới thành "Đã duyệt".')
    kv('Quy tắc kiểm soát', 'Người tạo báo giá không được tự duyệt (trừ admin); người duyệt cấp 1 '
       'không được duyệt cấp 2 (4 mắt).')
    kv('Thông báo tự động', 'Khi chuyển "Chờ CEO duyệt" → CEO nhận thông báo (chuông 🔔). '
       'Khi được duyệt/bị từ chối → người tạo nhận thông báo.')
    kv('Bấm "Tạo đơn"', 'Sinh ĐƠN BÁN thật (kèm dòng hàng từ báo giá) → chuyển sang luồng Đơn bán (2.5).')

    h('2.4. Hợp đồng', 2)
    kv('Mục đích', 'Văn bản cam kết với khách, có thể sinh từ báo giá đã duyệt.')
    flow('draft (Nháp) ─► pending_sign (Chờ ký) ─► active (Hiệu lực) ─► expired (Hết hạn)')
    kv('Tự hết hạn', 'Hợp đồng active quá ngày kết thúc sẽ được tác vụ định kỳ chuyển sang "expired".')

    h('2.5. Đơn bán (Sales Order) — nối CRM ↔ WMS', 2)
    kv('Mục đích', 'Đơn hàng thực tế để giao + thu tiền.')
    kv('Luồng', '')
    flow('draft ─(nút "Ký")─► active ─(nút "Giao")─► shipping ─► completed')
    flow('                                   └─[TỰ ĐỘNG sinh PHIẾU XUẤT WMS]')
    kv('Bấm "Ký"', 'Đơn chuyển "Hiệu lực" (active) — sẵn sàng giao.')
    kv('Bấm "Giao"', 'Đơn chuyển "Đang giao"; hệ thống TỰ TẠO phiếu xuất kho (WMS Outbound) '
       'gắn mã đơn → chuyển việc sang Kho để soạn & trừ tồn (xem 3.3).')
    kv('Thu tiền', 'Ghi nhận thanh toán → đã thu tăng → công nợ (tổng − đã thu) giảm → '
       'hiện ở màn Công nợ + báo cáo CEO.')

    h('2.6. Viếng thăm / Hoạt động (ghi âm + recap)', 2)
    kv('Mục đích', 'Lưu lại mọi lần tiếp xúc khách (gặp/gọi/email/Zalo) để theo dõi quan hệ.')
    flow('Gặp/gọi khách ─► (Tạo Visit/Activity) + tải Ghi âm + nhập Recap ─► LƯU')
    flow('   └────► hiện ở "Lịch sử làm việc" trong hồ sơ Khách hàng 360')
    kv('Nối sang', 'Mọi viếng thăm/hoạt động tự xuất hiện trên dòng thời gian của khách (Customer 360), '
       'kèm nút nghe ghi âm / tải file recap.')

    h('2.7. Dịch vụ (Ticket) ↔ Bảo hành ↔ Serial', 2)
    kv('Mục đích', 'Xử lý yêu cầu hỗ trợ/bảo hành; truy ngược tới sản phẩm đã bán.')
    flow('open ─► in_progress ─► resolved ─► closed')
    flow('Ticket gắn "serial" ◄──► tra "Lịch sử serial": đã bán cho ai, còn bảo hành không, ticket nào')
    kv('Liên kết 2 chiều', 'Từ ticket biết serial nào lỗi; từ serial (WMS) tra ngược ra khách đã mua + '
       'các ticket liên quan.')

    h('2.8. Import dữ liệu cũ (di trú)', 2)
    kv('Mục đích', 'Đưa dữ liệu trước khi có phần mềm (KH/Lead/Hợp đồng/Đơn) vào hệ thống.')
    flow('Tải mẫu ─► điền Excel ─► Chọn file ─► "Xem trước" (kiểm lỗi, CHƯA ghi) ─► "Import" (ghi)')
    kv('An toàn', 'Bản ghi trùng mã sẽ bị bỏ qua; dòng lỗi (thiếu mã, KH không tồn tại…) được báo riêng.')

    # ════════ 3. WMS — LUỒNG TỪNG TÍNH NĂNG ════════
    h('3. WMS — luồng từng tính năng', 1)

    h('3.1. Tồn kho & Lịch sử kho (sổ cái)', 2)
    kv('Mục đích', 'Biết còn bao nhiêu, ở ô nào; mọi biến động đều ghi vết.')
    kv('Nguyên tắc', 'Mọi thao tác nhập/xuất/điều chỉnh/chuyển kho đều tạo 1 dòng "Lịch sử kho" '
       '(StockMovement: ±số lượng, lý do, ô, người làm) để truy vết.')

    h('3.2. Nhập kho (Inbound)', 2)
    kv('Mục đích', 'Nhận hàng nhà cung cấp vào kho, cộng tồn.')
    kv('Luồng', '')
    flow('ASN (báo hàng về) ─(Đã về)─► PHIẾU NHẬP: draft')
    flow('   ─(nút "Quét" → quét từng mã + SL)─► cộng dồn "đã nhận" (confirmed)')
    flow('   ─(nút "Xác nhận nhận")─► CỘNG TỒN vào ô đích (putaway) + ghi Lịch sử kho (inbound)')
    kv('Bấm "Quét"', 'Mở cửa sổ quét theo phiếu: quét mã + nhập SL, hệ thống cộng dồn "đã nhận/cần nhận". '
       'Đủ thì bấm "Xác nhận nhận" để thực sự cộng tồn.')

    h('3.3. Xuất kho (Outbound)', 2)
    kv('Mục đích', 'Soạn & giao hàng cho khách, trừ tồn.')
    kv('Luồng', '')
    flow('Tạo phiếu xuất (hoặc TỰ SINH khi "Giao" đơn bán) : draft')
    flow('   ─(nút "Pick-list")─► gợi ý lấy ở ô nào (FIFO/FEFO)')
    flow('   ─(nút "Quét" → quét mã + ô + SL)─► TRỪ TỒN + cộng "đã soạn" (picking ─► picked)')
    flow('   ─(nút "Giao")─► shipped + ghi Lịch sử kho (outbound) + cập nhật serial đã bán')
    kv('Nối ngược CRM', 'Phiếu xuất mang mã đơn bán; khi giao xong, hàng đã trừ khỏi tồn.')

    h('3.4. Quét mã (camera điện thoại) — 4 chế độ', 2)
    kv('Mục đích', 'Thao tác kho nhanh bằng điện thoại, không cần đơn.')
    table(['Chế độ (tab)', 'Bấm xong thì', 'Kết quả'],
          [['Tra cứu', 'quét 1 mã', 'Hiện phụ tùng/serial khớp (không đổi tồn)'],
           ['Nhập kho', 'quét mã + ô + SL → Nhập kho', 'Cộng tồn ô đó'],
           ['Xuất kho', 'quét mã + ô + SL → Xuất kho', 'Trừ tồn (báo lỗi nếu thiếu)'],
           ['Kiểm kê', 'quét mã + ô + số đếm → Cập nhật tồn', 'Đặt tồn = số đếm']])

    h('3.5. Phiên kiểm kê (Cycle Count)', 2)
    kv('Mục đích', 'Đếm thực tế cả loạt, đối chiếu & điều chỉnh tồn một lần.')
    flow('"Phiên mới" ─► quét đếm từng ô (lưu: tồn hệ thống vs số đếm)')
    flow('   ─► xem BẢNG CHÊNH LỆCH (xanh: dư, đỏ: thiếu)')
    flow('   ─(nút "Áp dụng")─► đặt tồn = số đếm cho mọi dòng + ghi Lịch sử kho')
    kv('Khác "Quét → Kiểm kê"', 'Kiểm kê theo phiên ghi nhận trước, đối chiếu rồi mới áp dụng hàng loạt; '
       'còn quét-kiểm-kê ở màn Quét mã là chỉnh ngay từng mã.')

    h('3.6. Serial & Bảo hành', 2)
    flow('Nhập kho ─► serial: in_stock ─(bán/giao)─► sold (gắn khách + ngày bảo hành)')
    flow('   ─► màn Bảo hành: còn hạn / sắp hết / hết hạn ;  Lịch sử serial: ai mua, ticket nào')

    # ════════ 4. CEO ════════
    h('4. CEO — luồng tổng hợp', 1)
    kv('Mục đích', 'Nhìn toàn cảnh; KHÔNG nhập liệu, chỉ ĐỌC số liệu thật từ CRM + WMS + Sales.')
    flow('CRM/Sales (đơn, công nợ, cơ hội) + WMS (tồn) ──► CEO: KPI / Doanh thu / Công nợ / Forecast / Tồn')
    flow('AI Summary: gom tất cả ─(Làm mới)─► tóm tắt ;  ─(Tải Excel)─► xuất báo cáo .xlsx')

    # ════════ 5. TRỢ LÝ NỘI BỘ ════════
    h('5. Trợ lý nội bộ (chat) — lối tắt theo luồng', 1)
    para('Gõ câu lệnh; trợ lý thực hiện đúng bước trong luồng, theo quyền của bạn. '
         'Hành động ghi tạo BẢN NHÁP để bạn vào màn tương ứng duyệt/xác nhận tiếp.')
    table(['Câu lệnh', 'Tạo ra (bước trong luồng)', 'Bước kế tiếp do ai'],
          [['làm báo giá cho ABC: 5 x 001002', 'Báo giá nháp', 'Sale gửi → Manager duyệt'],
           ['soạn hợp đồng từ BG-0007', 'Hợp đồng nháp', 'Sale hoàn thiện'],
           ['nhập kho 100 x 001002', 'Phiếu nhập nháp', 'Kho xác nhận nhận'],
           ['xuất kho 20 x 001002', 'Phiếu xuất nháp', 'Kho soạn & giao'],
           ['đơn của ABC / tồn 001002', 'Tra cứu (đọc)', '—'],
           ['báo cáo điều hành / đánh giá kế hoạch', 'Báo cáo (đọc)', '—']])

    # ════════ 6. SƠ ĐỒ TRẠNG THÁI GỌN ════════
    h('6. Bảng tra nhanh trạng thái', 1)
    table(['Đối tượng', 'Các trạng thái (theo thứ tự luồng)'],
          [['Lead', 'new → contacted → qualified → converted / lost'],
           ['Cơ hội', 'prospect → qualify → proposal → negotiate → won / lost'],
           ['Báo giá', 'draft → sent → (pending_ceo) → approved → converted / rejected'],
           ['Hợp đồng', 'draft → pending_sign → active → expired / cancelled'],
           ['Đơn bán', 'draft → active (ký) → shipping (giao) → completed / cancelled'],
           ['Phiếu nhập', 'draft → confirmed → putaway'],
           ['Phiếu xuất', 'draft → picking → picked → shipped'],
           ['Phiếu kiểm kê', 'open → applied'],
           ['Serial', 'in_stock → sold'],
           ['Ticket', 'open → in_progress → resolved → closed']])

    d.save(out)
    print(f'Saved: {out}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'HUONG_DAN_LUONG_NGHIEP_VU.docx')
