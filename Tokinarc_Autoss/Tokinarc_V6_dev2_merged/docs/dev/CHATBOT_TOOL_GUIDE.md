# CHATBOT TOOL GUIDE — Thêm tool mới end-to-end

> ⚠️ **TÀI LIỆU LỖI THỜI (kiến trúc chatbot CŨ).** File này mô tả chatbot sidecar JWT + 27 tool gọi Django REST — KHÔNG còn dùng. Chatbot THẬT hiện tại là FastAPI v8.0 độc lập (X-API-Key + retrieval tự chứa, 11 tool in-process). Đọc `chatbot/README.md` và `docs/implementation/V6_MERGE_chatbot_real.md` để biết kiến trúc đúng. Giữ file này chỉ để tham khảo lịch sử thiết kế.


> **Mục tiêu**: cho phép Gemini gọi 1 capability mới của hệ thống qua chat.
> **Thời gian**: ~30 phút cho tool đơn giản (read), ~1 giờ cho tool ghi.

---

## Khi nào cần thêm tool?

| Tình huống | Có cần tool mới? |
|---|---|
| Sale hỏi qua chat "cho tôi xem báo giá BG-0042" | Đã có `get_quote` chưa? Nếu có thì dùng. |
| CEO hỏi "lợi nhuận tháng" | Cần tool `get_profit_monthly` mới (chưa có) |
| Khách hỏi giá 1 mã không trong DB | Không cần tool — `search_parts` đã đủ |
| Sale muốn copy 1 báo giá cũ | Cần tool `clone_quote` mới |

Nguyên tắc: **1 capability = 1 tool**. Đừng dồn 5 thao tác vào 1 tool "siêu" — LLM dễ nhầm.

---

## Anatomy: 1 tool đi qua 5 file

Khi LLM gọi tool, dữ liệu chảy qua 5 file. Hiểu cấu trúc này = thêm tool nhanh:

```
1. backend/apps/<app>/views.py          ← endpoint Django REST thật
2. backend/apps/accounts/roles.py       ← khai quyền (READ/WRITE_TOOL_REQUIREMENTS)
3. chatbot/tool_clients.py              ← method HTTP gọi endpoint (1)
4. chatbot/gemini_planner.py            ← schema JSON cho Gemini function calling
5. chatbot/tool_guardrail.py            ← (nếu tool nhận positional) _TOOL_CALL_SPEC
```

Quy trình:
```
LLM quyết định gọi tool
  → planner (file 4) đã filter tool theo role (file 2)
  → guardrail.guard() (file 5) check lần cuối
  → tool_clients (file 3) gọi HTTP đến views.py (file 1)
  → Django enforce permission cuối cùng
  → trả về LLM compose response
```

---

## Worked example: thêm tool `get_quote`

Yêu cầu: Sale hỏi "cho tôi xem báo giá BG-2026-0042" → bot tra detail quote.

### Bước 1: Verify endpoint Django đã có

```bash
cd backend
DJANGO_SETTINGS_MODULE=tokinarc.settings.test python -c "
import django; django.setup()
from django.urls import reverse
print(reverse('quote-detail', args=['some-uuid']))
"
# → /api/v1/crm/quotes/some-uuid/
```

`QuoteViewSet` đã có `retrieve` action mặc định → endpoint sẵn sàng. Không cần code backend mới.

### Bước 2: Khai quyền trong `accounts/roles.py`

Đây là tool **đọc**. Đi qua `READ_TOOLS` (mọi role nội bộ đọc được) hoặc `READ_TOOL_REQUIREMENTS` (chỉ role cụ thể).

`get_quote` không nhạy cảm tài chính → chỉ thêm vào `READ_TOOLS`:

```python
# backend/apps/accounts/roles.py
READ_TOOLS: frozenset[str] = frozenset({
    'search_parts', 'get_part', 'get_torch',
    'get_customer', 'get_customer_360', 'list_customers',
    'get_inventory', 'get_serial_history',
    'get_quote',   # ← THÊM dòng này
    'get_kpi_overview', 'get_revenue_monthly', ...
})
```

> **Nếu** tool chỉ cho 1 role cụ thể, thêm vào `READ_TOOL_REQUIREMENTS`:
> ```python
> READ_TOOL_REQUIREMENTS: dict[str, frozenset[str]] = {
>     'get_quote': frozenset({Role.SALES, Role.MANAGER, Role.ADMIN}),
>     ...
> }
> ```

### Bước 3: Sinh lại `roles_generated.py` cho chatbot

```bash
cd backend
python manage.py dump_roles --format=py --out ../chatbot/roles_generated.py
# → Đã ghi py → ../chatbot/roles_generated.py
```

> **Quan trọng**: bước này bắt buộc. CI sẽ exit 1 nếu file sinh không khớp `roles.py` (xem `.github/workflows/ci.yml` step "Check role tables sync"). Bỏ qua = local pass, CI đỏ.

### Bước 4: Thêm client method `tool_clients.py`

```python
# chatbot/tool_clients.py
class ToolClient:
    # ... các method khác ...

    async def get_quote(self, quote_id: str) -> dict:
        """Lấy chi tiết 1 báo giá theo quote_id (UUID)."""
        return await self._request('GET', f'/crm/quotes/{quote_id}/')
```

**Quy ước method**:
- `async def` (loop chính chạy async)
- Param positional cho ID đơn lẻ (`quote_id`, `customer_id`), `*, kw=...` cho query filter
- Docstring 1 dòng — Gemini đọc làm description
- Return `dict` (response JSON) — exception map qua `_request`

### Bước 5: Thêm schema cho Gemini `gemini_planner.py`

```python
# chatbot/gemini_planner.py
_TOOL_SCHEMAS: dict[str, dict] = {
    # ... các tool khác ...

    "get_quote": {
        "description": "Lấy chi tiết 1 báo giá theo quote_id (UUID).",
        "parameters": {"type": "object", "properties": {
            "quote_id": {"type": "string", "description": "UUID của báo giá"}
        }, "required": ["quote_id"]},
    },
}
```

**Chú ý schema**:
- `description` ngắn gọn — Gemini dùng để quyết định có gọi tool này không
- `required` field — Gemini sẽ hỏi user nếu thiếu
- Description từng field — giúp Gemini extract đúng từ câu hỏi tự nhiên

### Bước 6: Verify CI smoke test pass

`chatbot/test_chatbot_smoke.py::test_all_27_tools_have_schema` so AST `tool_clients.py` với `_TOOL_SCHEMAS`. Nếu lệch → fail. Vì bước 4 + 5 add cùng tool → khớp 28/28.

```bash
cd chatbot && pytest test_chatbot_smoke.py -q
# → 6 passed (cần update `len(methods) == 27` thành 28)
```

Sửa số trong test:

```python
def test_all_27_tools_have_schema():   # rename hoặc để nguyên
    # ...
    assert len(methods) == 28           # ← đổi 27 → 28
```

### Bước 7: Test end-to-end với JWT

```bash
# 1. Backend running
cd backend && python manage.py runserver

# 2. Chatbot running
cd chatbot && uvicorn main:app --port 8080 --reload

# 3. Tạo token sale
TOKEN=$(python -c "import jwt; print(jwt.encode({'sub':'u1','username':'sale1','role':'sales'}, 'dev', algorithm='HS256'))")

# 4. Tạo quote (qua admin) hoặc đã có sẵn
# 5. Gọi tool trực tiếp
curl -X POST http://localhost:8080/api/v1/tool/dispatch \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tool":"get_quote","payload":{"quote_id":"<existing-uuid>"}}'
# → {"ok": true, "data": {<quote detail>}}
```

### Bước 8: Test qua Gemini (cần API key)

```bash
export GEMINI_API_KEY="..."
# Restart chatbot

curl -X POST http://localhost:8080/api/v2/query \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"Cho tôi xem báo giá BG-2026-0042 chi tiết"}'
# Gemini sẽ:
# 1. Hiểu cần get_quote
# 2. Hỏi user "Bạn cho tôi UUID của báo giá BG-2026-0042"  HOẶC
# 3. Tự gọi list_customers / search để tìm quote_id từ code
```

> **Tip**: Nếu muốn LLM hỗ trợ tốt cả khi user nhập code thay vì UUID, thêm logic ở backend: viewset `lookup_field='id'` nhưng allow lookup by `code` (custom `get_object()`).

---

## Worked example 2: thêm tool ghi `cancel_quote`

Yêu cầu: Manager hủy 1 quote draft/sent (đặt status = `rejected`).

### Khác gì so với tool đọc

3 chỗ khác biệt:

1. **Endpoint backend phải mới** (POST action)
2. **`WRITE_TOOL_REQUIREMENTS`** thay vì `READ_TOOLS`
3. **`_TOOL_CALL_SPEC`** nếu method nhận positional (vd `cancel_quote(quote_id)`)

### Bước 1: Backend — viewset action mới

```python
# backend/apps/crm/views_ext.py — class QuoteViewSet
class QuoteViewSet(viewsets.ModelViewSet):
    # ... action approve, to_contract đã có ...

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        """Hủy quote (chỉ manager/admin). Quote đã convert → 400."""
        quote = self.get_object()
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ manager hủy được.'}, status=403)
        if quote.status == QuoteStatus.CONVERTED:
            return Response({'detail': 'Quote đã chuyển order, không hủy được.'}, status=400)
        quote.status = QuoteStatus.REJECTED
        quote.save(update_fields=['status', 'updated_at'])
        publish(Channel.QUOTE_REJECTED, {'quote_id': str(quote.id)})
        _audit(request, 'cancel_quote', 'crm.Quote', quote.id)
        return Response(QuoteSerializer(quote).data)
```

> Thêm `Channel.QUOTE_REJECTED` trong `tokinarc/eventbus/channels.py` nếu chưa có (xem [`EVENTS_HANDLERS.md`](EVENTS_HANDLERS.md)).

### Bước 2: Test backend trước

```python
# backend/apps/crm/tests/test_crm_ext.py
@pytest.mark.django_db
def test_cancel_quote_manager_only(manager, sale):
    cust = CustomerFactory(owner=sale)
    sc = APIClient(); sc.force_authenticate(sale)
    q = sc.post('/api/v1/crm/quotes/', {...}, format='json').data

    # Sale không hủy được
    r1 = sc.post(f"/api/v1/crm/quotes/{q['id']}/cancel/")
    assert r1.status_code == 403

    # Manager hủy được
    mc = APIClient(); mc.force_authenticate(manager)
    r2 = mc.post(f"/api/v1/crm/quotes/{q['id']}/cancel/")
    assert r2.status_code == 200
    assert r2.data['status'] == 'rejected'
```

### Bước 3: roles.py + dump_roles

```python
# backend/apps/accounts/roles.py
WRITE_TOOL_REQUIREMENTS: dict[str, frozenset[str]] = {
    # ...
    'cancel_quote': frozenset({Role.MANAGER, Role.ADMIN}),
}
```

```bash
python manage.py dump_roles --format=py --out ../chatbot/roles_generated.py
```

### Bước 4: tool_clients.py — method nhận positional

```python
async def cancel_quote(self, quote_id: str) -> dict:
    """Hủy báo giá (chỉ manager+). Không hủy được nếu đã convert."""
    return await self._request('POST', f'/crm/quotes/{quote_id}/cancel/')
```

### Bước 5: gemini_planner schema

```python
"cancel_quote": {
    "description": "Hủy báo giá (đặt status=rejected). CHỈ manager/admin.",
    "parameters": {"type": "object", "properties": {
        "quote_id": {"type": "string"}
    }, "required": ["quote_id"]},
},
```

### Bước 6: tool_guardrail — **bắt buộc** thêm `_TOOL_CALL_SPEC`

Vì method nhận positional `(quote_id)`:

```python
# chatbot/tool_guardrail.py
_TOOL_CALL_SPEC: dict[str, dict] = {
    # ... các tool khác ...
    'cancel_quote': {'positional': ['quote_id']},  # ← THÊM
}
```

**Nếu quên bước này**: `_call_method` fallback dùng `method(payload)` (truyền dict), method nhận positional → **TypeError** crash bot.

### Bước 7: smoke test

```bash
cd chatbot && pytest test_chatbot_smoke.py -q
# `test_all_27_tools_have_schema` sẽ check count + AST match
```

---

## Phân loại tool dispatch

`_call_method` (trong `tool_guardrail.py`) chọn cách gọi method dựa trên `_TOOL_CALL_SPEC`:

| Kiểu | Khi nào | Khai trong `_TOOL_CALL_SPEC` | Ví dụ method |
|---|---|---|---|
| **positional** | Method nhận 1+ tham số positional | `{'positional': ['x', 'y']}` | `move_opportunity_stage(opp_id, stage)` |
| **dict** | Method nhận nguyên payload dict | `{'dict': True}` | `create_quote(payload)` |
| **kwargs** (default cho READ) | Method nhận `**kwargs` | KHÔNG khai (auto cho `READ_TOOLS`) | `search_parts(query='x', top_k=5)` |
| **no-arg** | Method `()` không tham số | KHÔNG khai + payload rỗng | `get_revenue_monthly()` |

**Quy tắc nhanh**: nếu method chữ ký có `(self, x, y)` → positional. Nếu `(self, payload: dict)` → dict. Nếu `(self, *, a=None, b=None)` → kwargs.

---

## Phân quyền chatbot — 3 lớp chi tiết

Khi LLM cố gọi tool, 3 lớp chặn lần lượt:

### Lớp 1: `gemini_planner.allowed_tools_for(role)`

Trước khi gửi tool list cho Gemini, filter:

```python
def allowed_tools_for(role: str) -> list[str]:
    out = []
    customer_ok = {"search_parts", "get_part", "get_torch"}
    for tool in _TOOL_SCHEMAS:
        if role == "customer":
            if tool in customer_ok:
                out.append(tool)
            continue
        if tool in WRITE_TOOL_REQUIREMENTS:
            if role in WRITE_TOOL_REQUIREMENTS[tool]:
                out.append(tool)
        elif tool in READ_TOOL_REQUIREMENTS:
            if role in READ_TOOL_REQUIREMENTS[tool]:
                out.append(tool)
        elif tool in READ_TOOLS:
            out.append(tool)
    return out
```

→ Gemini **không thấy** tool nó không được phép. Giảm khả năng LLM cố gọi bậy.

### Lớp 2: `tool_guardrail.guard()` + `_per_tool_check`

Ngay cả khi LLM cố gọi tool ngoài (vd qua jailbreak), guardrail block:

```python
def guard(tool_name, user_ctx, *, payload=None) -> ToolDecision:
    if user_ctx.role == Role.CUSTOMER:
        if tool_name in WRITE_TOOL_REQUIREMENTS:
            return _deny(..., 'CUSTOMER_NO_WRITE', ...)
        # ... thêm check khác
    if tool_name in WRITE_TOOL_REQUIREMENTS:
        if user_ctx.role not in WRITE_TOOL_REQUIREMENTS[tool_name]:
            return _deny(..., 'ROLE_DENIED', ...)
    extra = _per_tool_check(tool_name, user_ctx, payload or {})
    # ...
```

`_per_tool_check` có business rule cụ thể:

```python
if tool_name == 'approve_quote' and ctx.role == Role.SALES:
    return _deny(..., 'SELF_APPROVE_FORBIDDEN', ...)
```

### Lớp 3: Django REST permission

Cuối cùng — endpoint Django enforce. `IsManagerOrAdmin`, `OwnedObjectPermission`, etc. Đây là tầng **không thể bypass** vì sidecar gọi qua HTTP + JWT của user.

---

## Checklist khi thêm tool

Copy-paste ra ticket / PR description:

```
□ Endpoint Django đã có / mới (file: ___)
□ Test backend cho endpoint (file: ___)
□ Thêm vào WRITE_TOOL_REQUIREMENTS / READ_TOOLS trong roles.py
□ Chạy `dump_roles --format=py --out ../chatbot/roles_generated.py`
□ Thêm method vào tool_clients.py với docstring
□ Thêm schema vào gemini_planner._TOOL_SCHEMAS
□ Nếu method nhận positional → thêm _TOOL_CALL_SPEC
□ Update count test_all_27_tools_have_schema → 28
□ Smoke test: pytest chatbot/test_chatbot_smoke.py
□ Backend test: pytest backend/apps/ -q
□ Test thủ công qua curl /tool/dispatch
□ Test E2E qua /api/v2/query với Gemini key (nếu có)
□ Update CHATBOT_TOOL_GUIDE.md nếu pattern mới phát sinh
```

---

## Anti-patterns — đừng làm

### ❌ Chatbot tool ghi DB trực tiếp

```python
# SAI — vi phạm Django source of truth
async def cancel_quote(self, quote_id: str):
    import psycopg2
    conn = psycopg2.connect(...)
    conn.cursor().execute("UPDATE crm_quote SET status='rejected' WHERE id=%s", [quote_id])
```

**Đúng**: gọi qua HTTP với JWT của user.

### ❌ Hardcode role check trong tool_clients

```python
# SAI — duplicate logic guardrail
async def get_revenue_monthly(self):
    if self.user_role not in ('manager', 'admin'):
        raise PermissionError()  # ← KHÔNG
    return await self._request('GET', '/analytics/revenue/monthly/')
```

**Đúng**: để guardrail (lớp 2) + Django (lớp 3) chặn. tool_clients chỉ là HTTP wrapper.

### ❌ Tool "siêu" làm nhiều việc

```python
# SAI — 1 tool 3 việc
async def handle_quote_workflow(self, quote_id, action, payload):
    if action == 'approve': ...
    elif action == 'cancel': ...
    elif action == 'convert': ...
```

LLM dễ nhầm. **Đúng**: 3 tool riêng `approve_quote`, `cancel_quote`, `quote_to_contract`.

### ❌ Tool đọc thông tin nhạy cảm không qua READ_TOOL_REQUIREMENTS

```python
# SAI — sale đọc được lương manager
READ_TOOLS = frozenset({'get_user_payroll', ...})   # không nhạy cảm enforce
```

**Đúng**:
```python
READ_TOOL_REQUIREMENTS = {
    'get_user_payroll': frozenset({Role.ADMIN}),  # admin only
}
```

---

## Debug khi tool không hoạt động

| Triệu chứng | Debug |
|---|---|
| Bot không thấy tool | Check `allowed_tools_for(role)` trả list có tool không. Verify roles.py + roles_generated.py khớp. |
| Bot gọi nhưng lỗi 403 | Check `guard()` log "guardrail_deny" — code = `ROLE_DENIED` / `SELF_APPROVE_FORBIDDEN` / `CUSTOMER_NO_WRITE`. Backend permission cũng có thể chặn. |
| Bot gọi nhưng TypeError | Method nhận positional nhưng quên `_TOOL_CALL_SPEC`. Kiểm tra log "MISSING_ARG" hay TypeError trace. |
| Bot trả "không có thông tin" | `_call_method` trả OK nhưng data rỗng. Check curl direct endpoint xem có data không. |
| Gemini không hiểu nên gọi tool gì | Description schema không rõ. Cải thiện docstring + tên field. |

---

## Roadmap chatbot

Việc còn lại để chatbot hoàn thiện production:

1. **WebSocket `/ws/query`** — streaming response (port từ `main_legacy_v5.py`)
2. **Session memory** — giữ context giữa các turn (hiện mỗi message là fresh start)
3. **Compose response Vietnamese** — Gemini đã trả tiếng Việt nhưng có thể tune prompt thêm
4. **Tool retry on transient error** — `_request` đã retry 3 lần ở backend HTTP layer
5. **Cost tracking** — log token usage Gemini per query để biết RỦI RO cost
