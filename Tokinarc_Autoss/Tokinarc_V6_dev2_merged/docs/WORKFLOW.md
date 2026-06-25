# Tokinarc V6 — Sơ đồ luồng nghiệp vụ (CRM · WMS · CEO)

> Hệ thống ERP cho AUTOSS (phân phối súng hàn): Django + React + FastAPI chatbot + PostgreSQL.
> Tài liệu mô tả mối liên hệ giữa các tính năng và luồng nghiệp vụ end‑to‑end.

---

## 1. Tổng thể — 3 tab, ai làm gì

```
┌─────────────── CRM ───────────────┐   ┌─────────── WMS ───────────┐   ┌──── CEO ────┐
│ sale · manager                    │   │ NV kho · QL kho           │   │ ceo         │
│ Lead→KH→Cơ hội→Báo giá→Đơn→HĐ→Thu │   │ Tồn·Nhập·Xuất·Mua·Kiểm kê │   │ Duyệt + AI  │
└───────────────┬───────────────────┘   └────────┬──────────────────┘   └──────┬──────┘
                │           ┌──── DỊCH VỤ ────┐    │                            │
                │           │ kỹ sư: Ticket   │    │                            │
                └───────────┴────────┬────────┴────┴────────────────────────────┘
                          (admin: thấy & quản trị tất cả)
```

**3 trục chính:**
1. **Order-to-Cash** — bán hàng: CRM ↔ WMS ↔ CEO
2. **Procure-to-Pay** — mua hàng: WMS ↔ CEO (nuôi giá vốn cho CRM)
3. **Dịch vụ sau bán** — ticket kỹ sư

**Nguyên tắc cô lập tab:** mỗi vai trò chỉ thấy tab + tính năng của mình; chỉ admin thấy tất cả.

---

## 2. LUỒNG CRM — "Từ khách đến tiền" (Order-to-Cash)

```
                          ╔═══════════════ NGUỒN VÀO ═══════════════╗
                          ║ Chatbot khách  │  Nhập tay  │  Import   ║
                          ╚════════╤════════╧═════╤══════╧═════╤═════╝
                                   ▼              ▼            ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  LEAD                                                  [sale]       │
   │  new → contacted → qualified → converted / lost                    │
   │  🔔 chatbot đưa lead → sale "gọi khách"                            │
   │  Quản lý GIAO lead cho sale khác (🔔 người nhận)                   │
   └───────────────────────────────┬───────────────────────────────────┘
                                    │ "Chuyển KH" (convert)
                                    ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  KHÁCH HÀNG (công ty)          [sale sở hữu · manager thấy hết]    │
   │  + Người liên hệ · Customer 360 (đơn·công nợ·ticket·hoạt động)     │
   │  Quản lý GIAO khách cho sale khác (🔔)                             │
   └───────────────────────────────┬───────────────────────────────────┘
                                    │ tạo
                                    ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  CƠ HỘI (Opportunity)  →  PIPELINE (phễu kéo-thả)                  │
   │  prospect → qualify → proposal → negotiate → won / lost            │
   │  Giá trị × xác suất = Forecast (weighted)                          │
   └───────────────────────────────┬───────────────────────────────────┘
                                    │ tạo báo giá
                                    ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  BÁO GIÁ (Quote)   giá bán từ Catalog · Chiết khấu %               │
   │  draft → sent → (pending_ceo) → approved → converted               │
   │  💰 Lãi gộp = giá bán − giá vốn(WAC)  [chỉ manager/CEO]            │
   └───────────────────────────────┬───────────────────────────────────┘
                                    │ ĐỊNH TUYẾN DUYỆT THEO CK%
              ┌─────────────────────┼─────────────────────────┐
              ▼                     ▼                          ▼
        CK ≤ 5% (sale)        CK ≤ 10% (manager)         CK > 10% (CEO)
        tự duyệt              🔔 manager duyệt           🔔 CEO duyệt cấp 2
        → approved 🔔 sale    → approved 🔔 sale         → approved 🔔 sale
              └─────────────────────┼─────────────────────────┘
                                    │ "Chuyển" (approved)
                          ┌─────────┴──────────┐
                          ▼                    ▼
   ┌──────────────────────────┐   ┌──────────────────────────────────┐
   │  HỢP ĐỒNG (Contract)     │   │  ĐƠN BÁN (SalesOrder)            │
   │  draft→pending_ceo→       │   │  draft → pending(chờ ký)         │
   │  pending_sign → ACTIVE    │   │       → ACTIVE → shipping         │
   │  (xuất Word, ký)          │   │       → completed                 │
   │  🔔 ký xong → hiệu lực    │   └─────────────┬────────────────────┘
   └──────────────────────────┘                 │ ① KÝ
                                                 ▼
                              ╔════════ NỐI SANG WMS ════════╗
                              ║ tạo PHIẾU XUẤT KHO  🔔 NV kho ║
                              ║ kho soạn (FIFO/FEFO)          ║
                              ║ → trừ tồn + trừ giá vốn       ║
                              ║ ② GIAO xong  🔔 sale          ║
                              ╚═══════════════╤══════════════╝
                                              ▼ về lại CRM
   ┌──────────────────────────────────────────────────────────────────┐
   │  ③ HÓA ĐƠN (MISA) → ④ THU TIỀN → ⑤ CÔNG NỢ = tổng − đã thu       │
   │  🔔 (cron) công nợ quá hạn → sale                                 │
   └───────────────────────────────┬──────────────────────────────────┘
                                    ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  DASHBOARD (manager): KPI · Cơ hội sắp chốt · Hiệu suất Sale ·    │
   │  Doanh thu   →   CEO: AI Summary tổng hợp toàn bộ                 │
   └──────────────────────────────────────────────────────────────────┘
```

**Luồng phụ chạy song song:**
```
HOẠT ĐỘNG (gắn KH/Cơ hội): Visit Report(+GPS+recap) · Gọi/Email/Zalo(ghi âm) · Nhật ký
                            └──▶ Customer 360 timeline ──▶ CEO AI Summary
DỊCH VỤ: Khách báo lỗi → sale tạo TICKET(+serial) → giao kỹ sư 🔔 → xử lý → 🔔 báo lại
```

---

## 3. LUỒNG WMS — hàng vào ↔ tồn ↔ hàng ra

```
        ▲ HÀNG VÀO (Inbound)                          HÀNG RA (Outbound) ▼
╔══════════════════════════════╗              ╔══════════════════════════════════╗
║  MUA HÀNG  [QL kho lập]      ║              ║  Từ CRM: ĐƠN BÁN "Ký"            ║
║  Tồn thấp ──🔔──▶ lập PO     ║              ║  ──🔔──▶ NV kho "soạn hàng"      ║
║  + chọn Nhà cung cấp         ║              ╚════════════════╤═════════════════╝
║       │ requires CEO duyệt   ║                               ▼
║  🔔 CEO "Cần duyệt"          ║              ┌──────────────────────────────────┐
║       │ duyệt                ║              │ XUẤT KHO (Outbound)  [NV kho]    │
║  PO: draft→pending_ceo→      ║              │ draft→picking→picked→SHIPPED      │
║  APPROVED→ordered(đặt)       ║              │ • Pick FIFO/FEFO/NEAREST          │
╚═══════════╤══════════════════╝              │ • Quét lô (cảnh báo lệch FEFO)    │
            │ hàng về                         │ • TRỪ TỒN ở ô                     │
            ▼                                 │ • Từ chối giao ──🔔──▶ sale       │
┌──────────────────────────┐                  └────────────────┬─────────────────┘
│ ASN (báo hàng về)        │                                   │ giao xong 🔔 sale
│ + NHẬP KHO (Inbound)     │                                   ▼ → Đơn bán completed
│ draft→confirmed→          │                          (về CRM: Hóa đơn→Thu)
│ partial→PUTAWAY           │
│ 🔔 NV kho "nhận hàng"     │            ╔════════════ TỒN KHO (lõi) ════════════╗
│ • Nhận theo PO            │            ║  InventoryItem = (Ô × Mã) → số lượng  ║
│ • + TỒN vào ô            │───────────▶║  tồn / giữ(reserved) / khả dụng       ║
│ • + GIÁ VỐN (WAC) ───┐   │            ║  Tồn kho · Chỉ sắp hết (≤ định mức)   ║
└──────────────────────┼───┘            ║  Điều chỉnh ──🔔──▶ quản lý           ║
                       │                ║  Chuyển kho (ô→ô)                     ║
       ┌───────────────┘                ╚═══════╤═══════════════╤═══════════════╝
       ▼ nuôi giá vốn                            │               │
┌──────────────────────────┐            ┌────────┘               └────────┐
│ CATALOG (Part/Torch)     │            ▼                                  ▼
│ giá vốn → LÃI GỘP báo giá│     ┌──────────────┐                 ┌──────────────────┐
│ (CRM, manager thấy)      │     │ TRUY XUẤT    │                 │ KIỂM KÊ          │
└──────────────────────────┘     │ • Serial(cái)│                 │ open→APPLIED      │
                                 │ • Lô (FEFO)  │                 │ đếm → set tồn +   │
                                 └──────────────┘                 │ 🔔 lệch → quản lý │
                                                                  └──────────────────┘
```

**Cấu trúc kho (nền tảng — mọi tồn nằm ở 1 ô):**
```
KHO (HCM) ─▶ ZONE (A: Thân súng…) ─▶ KỆ (K01) ─▶ TẦNG (T1-T4) ─▶ Ô (HCM-A-K01-T1-03)
   ├─ Kho & vị trí: thêm/sửa/xoá (chống xoá khi còn hàng)
   ├─ Bản đồ kho: ô nào chứa mã gì + ô tìm kiếm
   └─ Quét mã (zxing-wasm): quét → ra đúng ô
```

---

## 4. LUỒNG CEO — duyệt + tổng hợp (không thao tác nghiệp vụ)

```
        ┌──────────── mọi sự kiện cần duyệt ───────────┐
CRM ────┤ Báo giá CK>10% · Hợp đồng CK>10%             ├──▶ CEO "CẦN DUYỆT"
WMS ────┤ Đơn mua (PO)                                 │     duyệt / từ chối 🔔
        └──────────────────────────────────────────────┘
        ┌──────────── mọi hoạt động & số liệu ─────────┐
CRM+WMS ┤ doanh thu·công nợ·tồn·recap·ghi âm·kho·ticket├──▶ CEO "AI SUMMARY"
        └──────────────────────────────────────────────┘

CEO tab gồm:  Cần duyệt · Bảng điều hành (KPI/biểu đồ) · AI Summary ·
              Doanh thu · Công nợ · Forecast · Giá trị tồn
```

---

## 5. Vòng đời (trạng thái) các chứng từ

| Chứng từ | Vòng đời | Mô-đun |
|---|---|---|
| **Lead** | new → contacted → qualified → **converted** / lost | CRM |
| **Cơ hội** | prospect → qualify → proposal → negotiate → **won** / lost | CRM |
| **Báo giá** | draft → sent → *(pending_ceo)* → **approved** → converted / rejected / expired | CRM |
| **Hợp đồng** | draft → *(pending_ceo)* → pending_sign → **active** → expired / cancelled | CRM |
| **Đơn bán** | draft → pending(chờ ký) → **active** → shipping → **completed** / cancelled | CRM→WMS |
| **Đơn mua (PO)** | draft → pending_ceo → **approved** → ordered → partial → **received** | WMS↔CEO |
| **Nhập kho** | draft → confirmed → partial → **putaway** | WMS |
| **Xuất kho** | draft → picking → picked → partial → **shipped** | WMS |
| **Kiểm kê** | open → **applied** (set tồn) | WMS |
| **Ticket** | open → in_progress → resolved → closed | Dịch vụ |

---

## 6. Quan hệ dữ liệu (cái gì nối cái gì)

```
CATALOG (Part/Torch) ──┬──▶ WMS InventoryItem (tồn theo ô) ──▶ Bản đồ kho
   │ giá vốn (WAC)      ├──▶ WMS Serial / Lô               ──▶ Truy xuất / Bảo hành
   │ ◀── Đơn mua        └──▶ Báo giá ─▶ Đơn bán ─▶ Xuất kho ─▶ Hóa đơn
   │
KHÁCH HÀNG ──┬─▶ Người liên hệ   ├─▶ Cơ hội ─▶ Báo giá ─▶ Hợp đồng/Đơn ─▶ Công nợ
             ├─▶ Ticket (dịch vụ)
             └─▶ Hoạt động/Visit/Ghi âm ──▶ CEO AI Summary
```

### Điểm nối liên mô-đun
| Mắt xích | Nối tới | Để làm gì |
|---|---|---|
| Báo giá/HĐ **CK>10%** | CEO | Duyệt cấp 2 |
| Đơn bán **Ký** | WMS | Tạo phiếu xuất, trừ tồn |
| Nhập kho → **WAC** | CRM/Catalog | Tính lãi gộp báo giá |
| Đơn mua (PO) | CEO | Duyệt mua |
| Giao xong | CRM | Đơn completed → Hóa đơn |
| Serial | Dịch vụ | Tra bảo hành |
| Tồn/điều chỉnh/kiểm kê lệch | 🔔 quản lý | Giám sát |
| Toàn bộ số liệu/hoạt động | CEO | Báo cáo + AI Summary |

---

## 7. Phân quyền (ai làm được gì)

| Vai trò | Tab | Quyền chính |
|---|---|---|
| **sale** | CRM | Lead/KH/Cơ hội/Báo giá (CK≤5% tự duyệt)/Đơn/HĐ; chỉ thấy của mình |
| **manager** | CRM | + Duyệt báo giá CK≤10% · Dashboard toàn team · Hiệu suất sale · giá vốn/lãi gộp |
| **warehouse** (NV kho) | WMS | Tồn·Nhập·Xuất·Quét·Kiểm kê·nhận hàng (KHÔNG: mua hàng, sửa cấu trúc) |
| **wh_manager** (QL kho) | WMS | + Mua hàng·NCC·Điều chỉnh tồn·duyệt kiểm kê·Kho&vị trí·KPI |
| **service** (kỹ sư) | Dịch vụ | Hàng chờ ticket·Bảo hành·tra cứu KH/SP |
| **ceo** | CEO | Duyệt cấp 2 (báo giá/HĐ/PO) · báo cáo · AI Summary |
| **admin** | Tất cả | Quản trị user & phân quyền, thấy mọi tab |

---

## 8. Hệ thống thông báo (🔔) — sợi chỉ nối các mắt xích

| Sự kiện | Báo cho |
|---|---|
| Chatbot đưa lead · giao lead/khách | Sale (người nhận) |
| Báo giá/HĐ/PO cần duyệt | Quản lý / CEO |
| Đã duyệt / từ chối | Người tạo |
| Đơn bán ký → cần soạn hàng · PO duyệt → hàng về | NV kho |
| Giao xong · ticket xử lý xong | Sale / người tạo |
| Tồn sắp hết · lô sắp hết hạn · công nợ quá hạn | Liên quan |
| Điều chỉnh tồn lớn · kiểm kê lệch | Quản lý (giám sát) |
| Giao ticket cho kỹ sư | Kỹ sư |

---

## 9. Ba nguyên tắc vận hành

1. **Một chiều, tăng dần cam kết**: Lead → Khách → Cơ hội → Báo giá → Đơn/HĐ → Tiền.
2. **Duyệt theo % chiết khấu**: tự duyệt (≤5%) → manager (≤10%) → CEO (>10%, không giới hạn).
3. **Ký đơn = kích hoạt kho**: "Ký" là ranh giới CRM→WMS; "Giao xong" là WMS→CRM. Nhập nuôi giá vốn, xuất trừ tồn.

---

*Tài liệu sinh tự động — Tokinarc V6. Cập nhật khi nghiệp vụ thay đổi.*
