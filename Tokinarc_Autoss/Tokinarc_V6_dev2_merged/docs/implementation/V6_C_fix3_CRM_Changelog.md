# Tokinarc V6.C-fix3 — CRM mở rộng

**Ngày**: 17/06/2026 (sau fix2)
**Phạm vi**: Mục 1 trong "việc còn lại" — CRM mở rộng + kích hoạt 6 write tool (hết 404).

## Đã thêm

### Models (apps/crm/models.py)
- `Lead` (+ LeadStatus) — KH tiềm năng, có score, convert → Customer.
- `Opportunity` (+ OppStage) — cơ hội bán hàng gắn Customer.
- `Quote` + `QuoteLine` (+ QuoteStatus) — báo giá, total tính ở SERVER từ lines.
- `Visit` — báo cáo viếng thăm.
- `Ticket` (+ TicketStatus/Priority) — service ticket.

Tất cả theo pattern BaseModel/SoftDeleteMixin, index đặt tên tường minh (drift=0).

### API (serializers_ext.py + views_ext.py + urls.py)
Endpoint mới — KÍCH HOẠT 6 write tool trong chatbot/tool_clients.py:
```
POST /api/v1/crm/quotes/                       create_quote
POST /api/v1/crm/quotes/{id}/approve/          approve_quote   (chỉ manager+, chặn self-approve)
POST /api/v1/crm/quotes/{id}/to-contract/      quote_to_contract (chỉ khi approved)
POST /api/v1/crm/opportunities/{id}/move-stage/ move_opportunity_stage
POST /api/v1/crm/visits/                        create_visit
POST /api/v1/crm/tickets/                       create_ticket
```
Thêm: leads/ (+ convert/), opportunities/, tickets/ (+ resolve/).

### Business rules enforced
- `total_vnd` tính ở server từ lines — client/bot set bậy bị bỏ qua.
- `approve`: chỉ manager/admin; không tự duyệt báo giá của mình (trừ admin).
- `to-contract`: chỉ quote đã approved.
- Ownership: sale chỉ thấy bản ghi của mình; manager+ thấy hết.
- Mọi thao tác ghi → AuditLog (via=ui|bot).
- Code tự sinh: BG-xxxx (quote), TK-xxxx (ticket), HD-xxxx (contract), KH-xxxx (customer).

## Test
`apps/crm/tests/test_crm_ext.py` — 12 test:
- create lead/opp/quote/visit/ticket qua API thật
- total tính server (client set 999 → bị bỏ, đúng 1.200.000)
- chặn self-approve, manager approve + to-contract, to-contract chặn khi chưa approved
- move-stage hợp lệ + reject stage sai
- ownership (sale chỉ thấy quote của mình), chặn unauthenticated

**Kết quả**: `pytest apps/ -q` → **71 passed** (59 cũ + 12 mới). drift = 0.

## Còn lại (chưa làm trong fix3)
- 6 write tool sales/wms chưa có client: sign_order, ship_order, create_payment,
  wms_pick_confirm, wms_adjust_inventory, wms_transfer_stock.
- Wire Gemini function calling vào query_v2() (vẫn stub).
- Event handlers thật, MV SQL + seed_embeddings, frontend React.

---

## Bổ sung — Nối 6 write tool sales/wms (cùng đợt fix3)

Phát hiện: 6 tool ghi đã khai quyền trong roles.py nhưng THIẾU client method.
Backend endpoint đều ĐÃ CÓ sẵn — chỉ cần nối client.

| Tool | Endpoint (đã có sẵn) | Role |
|------|----------------------|------|
| sign_order | POST /sales/orders/{id}/sign/ | manager/admin |
| ship_order | POST /sales/orders/{id}/ship/ | sales/warehouse/manager/admin |
| create_payment | POST /sales/payments/ | manager/admin |
| wms_pick_confirm | POST /wms/outbound/{id}/ship/ | warehouse/manager/admin |
| wms_adjust_inventory | POST /wms/inventory/adjust/ | warehouse/manager/admin |
| wms_transfer_stock | POST /wms/inventory/transfer/ | warehouse/manager/admin |

Thêm 6 client method vào `chatbot/tool_clients.py`. Verify:
- 6/6 endpoint resolve OK.
- Guardrail đúng: kho làm được pick/adjust/transfer; sale ship được nhưng
  KHÔNG sign/adjust/payment; manager full; khách bị chặn hết.

**Kết quả: 12/12 write tool giờ đã có client + endpoint + phân quyền.**
71 passed, drift=0, role sync khớp.

## Còn lại
- Wire Gemini function calling vào query_v2() (vẫn stub).
- Event handlers thật, MV SQL + seed_embeddings, frontend React.

---

## Bổ sung — Wire Gemini function calling vào query_v2() (cùng đợt fix3)

Thay block stub trong main.py bằng planner thật, **bật/tắt theo key**:
- CÓ GEMINI_API_KEY (hoặc GOOGLE_API_KEY) → gọi Gemini thật: function-calling
  loop chọn tool → dispatch_tool (guardrail) → compose câu trả lời.
- KHÔNG key → trả stub, pipeline vẫn chạy (dev không cần key).

### File mới
- `chatbot/gemini_planner.py` — function-calling loop (google-genai unified SDK),
  tool schema cho 8 tool chính, `allowed_tools_for(role)` lọc tool theo quyền.

### Defense-in-depth phân quyền (3 lớp)
1. `allowed_tools_for(role)` — Gemini CHỈ thấy tool role được phép.
2. `dispatch_tool → guard()` — chặn lần cuối kể cả LLM cố gọi tool ngoài.
3. Django REST permission — tầng chặn thật cuối cùng.
Verify: sale không thấy get_revenue_monthly trong tool list; nếu cố gọi qua
dispatch vẫn bị READ_ROLE_DENIED.

### Sửa version (BLOCKER tiềm ẩn)
- `google-genai==0.3.0` → `1.21.1`: bản 0.3.0 KHÔNG có API
  `client.aio.models.generate_content` / `types.FunctionDeclaration` mà code dùng
  → sẽ ImportError/AttributeError lúc chạy. Đã verify API khớp 1.21.1.
- `httpx==0.27.0` → `0.28.1`: google-genai mới yêu cầu httpx>=0.28.1 (xung đột
  dependency, sẽ vỡ `pip install` / `docker build`).
- `.env.example`: làm rõ GEMINI_API_KEY/GOOGLE_API_KEY/GEMINI_MODEL, để trống = stub.

### Test
`chatbot/test_chatbot_smoke.py` — 4 test: planner tắt khi không key, tool filter
theo role (khách/sale/manager), input guardrail block injection. 4 passed.

**Tổng kết fix3**: 71 backend + 4 chatbot smoke passed. 12/12 write tool có client.
Bot trả lời thật khi có key, stub khi chưa — dev chạy được ngay.

## Còn lại
- Event handlers thật (apps/<app>/handlers.py), MV SQL + seed_embeddings, frontend.
- WebSocket /ws/query streaming (port từ V5).

---

## Bổ sung — Khai đủ 27 tool schema cho Gemini + sửa bug dispatch

### Khai schema đủ bộ
`gemini_planner._TOOL_SCHEMAS`: 8 → **27 schema** (khớp đúng 27 client method,
không thừa/thiếu). Bot giờ tự gọi được TOÀN BỘ tool qua chat. Lọc theo role:
khách 3 / sale 14 / kho 12 / service 9 / manager+admin 27.

### Bug đã phát hiện & sửa (dispatch_tool)
**Vấn đề**: dispatch gọi `method(payload)` cho mọi write tool. Nhưng nhiều write
tool nhận POSITIONAL (approve_quote(quote_id), move_opportunity_stage(opp_id,
stage), sign_order, ship_order, quote_to_contract, wms_pick_confirm). Truyền
nguyên dict → sai URL hoặc TypeError (move_opportunity_stage CRASH).
→ Bot sẽ vỡ ngay khi gọi các tool này, dù schema đã khai.

**Fix**: thêm `_TOOL_CALL_SPEC` + `_call_method()` trong tool_guardrail.py — map
payload đúng chữ ký: positional / dict / kwargs. Thiếu tham số → MISSING_ARG
(không crash). Sửa luôn enum stage lệch (contact→prospect/qualify khớp OppStage).

### Test
`test_chatbot_smoke.py` +2 test: `_call_method` map đúng 4 kiểu gọi + chặn thiếu
arg; assert 27/27 tool có schema. Tổng: 6 chatbot smoke + 71 backend passed.

---

## Bổ sung — Frontend React slice 1 (login + Khách hàng)

Frontend đi từ skeleton (chỉ package.json) → **app chạy được, gọi API thật**.

### Đã thêm (frontend/src/)
- `lib/api.ts` — axios + JWT interceptor + auto-refresh (401 → refresh → retry).
- `lib/auth/store.ts` — zustand: login/logout/hasRole, persist user.
- `lib/types.ts` — type khớp serializer backend (User, Customer, Paginated).
- `App.tsx` — router + route guard (chưa login → /login).
- `pages/Login.tsx` — POST /auth/login/ thật, hiển thị lỗi backend.
- `pages/Customers.tsx` — GET /crm/customers/ thật: search (debounce), phân trang,
  loading/empty/error state.
- `components/Layout.tsx` — sidebar + topbar (user/role/logout).
- config: vite (proxy /api→Django), tsconfig, tailwind (palette công nghiệp), postcss.

### Verify
- `tsc --noEmit` sạch, `vite build` OK (322KB JS / 10KB CSS gzip 107KB).
- Test contract in-process (Django test Client) khớp shape frontend trông đợi:
  - login → {access, refresh, user{role, display_name}} ✓
  - /crm/customers/ → {count, results[code,name,segment,region,status,...]} ✓
  - không JWT → 401 ✓
  - ownership: manager thấy hết, sale chỉ thấy KH của mình ✓

### Còn lại (slice tiếp)
- Thêm trang WMS/CEO/Chatbot; ẩn menu theo role; biểu đồ (recharts có sẵn).
- E2E test (playwright đã cấu hình).
