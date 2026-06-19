# API REFERENCE — Backend HTTP endpoints

> **Base URL**: `http://localhost:8000/api/v1` (dev) hoặc `https://internal.tokinarc.vn/api/v1` (production)
> **Auth**: JWT Bearer trong header `Authorization: Bearer <access_token>` (trừ public catalog + login + JWKS)
> **Format**: JSON. Date: ISO 8601 (`2026-06-17`). Datetime: `2026-06-17T10:30:00Z`.

---

## Mục lục

1. [Authentication](#1-authentication)
2. [Catalog (public)](#2-catalog)
3. [CRM](#3-crm)
4. [Sales](#4-sales)
5. [WMS](#5-wms)
6. [Analytics (manager+)](#6-analytics)
7. [Storage](#7-storage)
8. [Mã lỗi chuẩn](#8-mã-lỗi-chuẩn)
9. [Phân trang + filter + search](#9-phân-trang--filter--search)

---

## 1. Authentication

### POST `/auth/login/`

**Body**:
```json
{"username": "admin", "password": "admin123"}
```

**Response 200**:
```json
{
  "access":  "eyJhbGc...",
  "refresh": "eyJhbGc...",
  "user": {
    "id": "01890b3...",
    "username": "admin",
    "display_name": "Quản trị",
    "full_name": "Quản trị",
    "email": "admin@tokinarc.vn",
    "phone": "",
    "role": "admin",
    "customer": null,
    "is_active": true,
    "date_joined": "2026-06-17T10:00:00Z"
  }
}
```

**Response 401** (`AUTH_INVALID`): sai mật khẩu / username không tồn tại.
**Response 429** (`RATE_LIMITED`): khóa tạm thời sau 5 lần fail liên tiếp / 15 phút.

```bash
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
```

### POST `/auth/refresh/`

```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh/ \
  -H 'Content-Type: application/json' \
  -d '{"refresh":"<refresh_token>"}'
# → {"access":"...","refresh":"..."}  (rotation = true)
```

### POST `/auth/logout/`

```bash
curl -X POST http://localhost:8000/api/v1/auth/logout/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"refresh":"<refresh_token>"}'
# → 204 No Content. refresh đã blacklist.
```

### GET `/auth/me/`

```bash
curl http://localhost:8000/api/v1/auth/me/ -H "Authorization: Bearer $TOKEN"
# → UserSerializer (giống user trong /auth/login/)
```

### GET `/.well-known/jwks.json` (public)

JWKS để FastAPI sidecar verify JWT. RS256 only — HS256 dev trả `{"keys":[]}`.

---

## 2. Catalog

> **Public** — không cần JWT. Khách Zalo tra cứu được. Throttle 20 req/min ở anon.

### GET `/catalog/parts/`

List Part có phân trang.

```bash
curl 'http://localhost:8000/api/v1/catalog/parts/?category=tip&ecosystem=P&page=1'
```

**Query params**:
- `category` — `nozzle`, `tip`, `liner`, `holder`, ...
- `ecosystem` — `P`, `D`, `O` (Panasonic / Daihen / OTC)
- `current_class` — `350A`, `500A`, ...
- `is_priority_sell` — `true` / `false`
- `ordering` — `tokin_part_no` | `category` | `price_vnd` | prefix `-` để desc

**Response 200**:
```json
{
  "count": 837, "next": "?page=2", "previous": null,
  "results": [
    {
      "tokin_part_no": "001005",
      "category": "nozzle",
      "ecosystem": "P",
      "current_class": "350A",
      "display_name_vi": "Chụp khí 350A",
      "display_name_en": "Nozzle 350A",
      "effective_price_vnd": 150000,
      "price_display": "150.000 ₫",
      "is_contact_price": false,
      "is_priority_sell": true
    }
  ]
}
```

### GET `/catalog/parts/{tokin_part_no}/`

Detail (full field).

```bash
curl http://localhost:8000/api/v1/catalog/parts/001005/
```

### GET `/catalog/parts/search/?q=...`

Search ILIKE trên `display_name_vi/en`, `tokin_part_no`, `p_part_nos`, `d_part_nos`, `o_part_nos` (alias OEM).

```bash
curl 'http://localhost:8000/api/v1/catalog/parts/search/?q=bep+1.2mm&top_k=5'
```

**Query params**:
- `q` — chuỗi tìm (≥2 ký tự, nếu không trả empty)
- `top_k` — max 50, default 10
- `ecosystem` — filter
- `category` — filter

### GET `/catalog/torches/` · `/{model_code}/` · `/search/`

Tương tự Part nhưng cho Torch (PK = `model_code`). Filter thêm: `family`, `cooling`.

```bash
curl 'http://localhost:8000/api/v1/catalog/torches/search/?q=RR-350'
```

---

## 3. CRM

> Cần JWT. Ownership filter: sale chỉ thấy bản ghi của mình; manager+ thấy hết.

### Customer

#### GET `/crm/customers/`

```bash
curl 'http://localhost:8000/api/v1/crm/customers/?segment=steel&search=Hop+kim' \
  -H "Authorization: Bearer $TOKEN"
```

**Query params**: `segment`, `status`, `region`, `owner`, `search` (code/name/tax_code), `ordering`.

#### POST `/crm/customers/`

```bash
curl -X POST http://localhost:8000/api/v1/crm/customers/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "code": "KH-0100",
    "name": "Cty TNHH Han Viet",
    "segment": "steel",
    "region": "HCM",
    "status": "active",
    "tax_code": "0316123456",
    "contacts": [
      {"full_name": "Nguyen Van A", "phone": "0901234567",
       "is_primary": true, "preferred_channel": "zalo"}
    ]
  }'
```

**Validation**:
- `code` phải bắt đầu bằng `KH-`
- Chỉ 1 primary contact mỗi customer

#### GET `/crm/customers/{id}/`

Detail với nested contacts.

#### PATCH `/crm/customers/{id}/`

Update partial. Nested contacts diff (giữ FK cho Activity/Visit).

#### DELETE `/crm/customers/{id}/`

Soft delete (`deleted_at = now`). Khôi phục qua admin panel.

#### GET `/crm/customers/{id}/360/`

Bundle data cho 360 view — orders + financial + opportunities + quotes + visits + tickets + installed machines.

```json
{
  "customer": {"id": "...", "code": "KH-0100", "name": "...", "segment": "steel", ...},
  "financial": {
    "order_count": 5,
    "revenue_vnd": 250000000,
    "collected_vnd": 200000000,
    "debt_vnd": 50000000
  },
  "contacts": [...],
  "recent_orders": [{"code": "HD-2026-0042", "total_vnd": 50000000, ...}],
  "opportunities": [...],
  "quotes": [...],
  "visits": [...],
  "tickets": [...],
  "installed_machines": [...]
}
```

### Lead

#### POST `/crm/leads/`

```bash
curl -X POST http://localhost:8000/api/v1/crm/leads/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "name": "Tran Van B",
    "company": "Cty ABC",
    "phone": "0901234567",
    "source": "zalo",
    "expected_value_vnd": 50000000
  }'
# → { "code": "LEAD-2026-0001", "status": "new", ... }
```

#### POST `/crm/leads/{id}/convert/`

Convert lead qualified → Opportunity + Customer.

```bash
curl -X POST http://localhost:8000/api/v1/crm/leads/$LEAD_ID/convert/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "customer_id": "<existing_customer_uuid>",
    "title": "Don 50 sung RR-350",
    "value_vnd": 80000000,
    "probability": 20
  }'
# → 201 + Opportunity detail
# Side effect: publish Channel.LEAD_QUALIFIED
```

### Opportunity

#### POST `/crm/opportunities/{id}/move-stage/`

```bash
curl -X POST http://localhost:8000/api/v1/crm/opportunities/$OPP_ID/move-stage/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"stage": "proposal"}'
# → 200 + Opportunity (probability auto-adjust: contact=10, proposal=30, negotiate=60, won=100, lost=0)
# Publishes Channel.OPPORTUNITY_STAGE
```

**Stages hợp lệ** (khớp `apps/crm/models.OppStage`):
`prospect` · `qualify` · `proposal` · `negotiate` · `won` · `lost`

### Quote

#### POST `/crm/quotes/`

```bash
curl -X POST http://localhost:8000/api/v1/crm/quotes/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "customer": "<customer_uuid>",
    "due_date": "2026-07-17",
    "notes": "Bao gia cho don 50 cai",
    "lines": [
      {"part_no": "001005", "qty": 50, "unit_price_vnd": 150000},
      {"part_no": "002010", "qty": 100, "unit_price_vnd": 12000}
    ]
  }'
```

**Quan trọng**:
- `total_vnd` **READ-ONLY**: server tự tính từ lines. Client gửi 999 → bị bỏ qua.
- `code` auto-sinh `BG-2026-0001`.
- Publishes `Channel.QUOTE_CREATED`.

#### POST `/crm/quotes/{id}/approve/`

```bash
curl -X POST http://localhost:8000/api/v1/crm/quotes/$QUOTE_ID/approve/ \
  -H "Authorization: Bearer $TOKEN"
# → 200, status = "approved"
```

**Permission**:
- Chỉ manager / admin
- Sale **không** tự duyệt quote của mình (trừ admin)
- Returns 403 nếu vi phạm

#### POST `/crm/quotes/{id}/to-contract/`

```bash
curl -X POST http://localhost:8000/api/v1/crm/quotes/$QUOTE_ID/to-contract/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"payment_terms": "net_30"}'
# → 201 { "order_code": "HD-2026-0001", "order_id": "..." }
# Side effect: tạo SalesOrder + SalesOrderLine, publish QUOTE_CONVERTED + ORDER_CREATED
```

**Constraint**: Chỉ chuyển được khi `status == approved`. Đã convert → 400.

### Visit

```bash
curl -X POST http://localhost:8000/api/v1/crm/visits/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "customer": "<uuid>",
    "visit_date": "2026-06-17",
    "purpose": "Demo san pham YMSA-500",
    "summary": "KH quan tam, hen bao gia ngay 20/6",
    "next_action": "Gui bao gia",
    "gps": {"lat": 10.762, "lng": 106.660}
  }'
```

### Ticket

```bash
curl -X POST http://localhost:8000/api/v1/crm/tickets/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "customer": "<uuid>",
    "title": "Sung han khong cap day",
    "description": "Hong sau 3 thang dung",
    "priority": "high",
    "serial_no": "SN12345"
  }'
# → 201, code = "TK-2026-0001"
# Publishes Channel.TICKET_OPENED
```

```bash
curl -X POST http://localhost:8000/api/v1/crm/tickets/$ID/resolve/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"resolution": "Thay bep han, test OK"}'
# → 200, status = "resolved"
```

---

## 4. Sales

### GET `/sales/orders/`

```bash
curl 'http://localhost:8000/api/v1/sales/orders/?status=active' \
  -H "Authorization: Bearer $TOKEN"
```

### POST `/sales/orders/{id}/sign/`

Manager+ ký đơn (draft/pending → active).

### POST `/sales/orders/{id}/ship/`

Sale/warehouse/manager+ cập nhật shipping (active → shipping).

### POST `/sales/payments/`

```bash
curl -X POST http://localhost:8000/api/v1/sales/payments/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "order": "<order_uuid>",
    "amount_vnd": 50000000,
    "paid_at": "2026-06-17",
    "method": "transfer",
    "reference": "TT-001"
  }'
# Publishes Channel.PAYMENT_RECEIVED → handler tự cập nhật paid_vnd + status nếu đủ
```

---

## 5. WMS

> Filter mọi list mặc định theo `?warehouse=<code>` (kho user thuộc).

### GET `/wms/inventory/?part_no=001005&warehouse=KHO-HCM`

```json
{
  "part_no": "001005",
  "warehouse": "KHO-HCM",
  "total_qty": 250,
  "bins": [
    {"bin_code": "A1-01", "qty": 100, "lot": "L20260601"},
    {"bin_code": "A1-02", "qty": 150, "lot": "L20260615"}
  ]
}
```

### POST `/wms/inventory/adjust/`

```bash
curl -X POST http://localhost:8000/api/v1/wms/inventory/adjust/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "bin": "A1-01",
    "part_no": "001005",
    "delta": -5,
    "reason": "hao hut kiem ke"
  }'
# Sinh StockMovement(kind=adjust, qty=-5, reason="...")
```

### POST `/wms/inventory/transfer/`

```bash
curl -X POST http://localhost:8000/api/v1/wms/inventory/transfer/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "from_bin": "A1-01",
    "to_bin": "B2-03",
    "part_no": "001005",
    "qty": 50
  }'
# 409 CONFLICT nếu from_bin không đủ qty
```

### POST `/wms/outbound/{id}/ship/`

Warehouse confirm xuất kho (kho → đường giao).

### GET `/wms/serials/{serial_no}/`

History 1 serial: nhập/xuất/bảo hành (cho service ticket).

---

## 6. Analytics

> **CHỈ** manager + admin. Sale/kho/khách → **403**.
> Hiện aggregate trực tiếp, kế hoạch chuyển MV (xem [`EVENTS_HANDLERS.md`](EVENTS_HANDLERS.md)).

```bash
# Tất cả endpoint không cần param
curl http://localhost:8000/api/v1/analytics/kpi/overview/         -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/v1/analytics/revenue/monthly/      -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/v1/analytics/revenue/by-segment/   -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/v1/analytics/debt-aging/           -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/v1/analytics/inventory/value/      -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/v1/analytics/forecast/pipeline/    -H "Authorization: Bearer $TOKEN"
```

**Shape mẫu** `/revenue/monthly/`:

```json
{
  "months": [
    {"month": "2026-04", "revenue_vnd": 1200000000, "collected_vnd": 900000000, "order_count": 23},
    {"month": "2026-05", "revenue_vnd": 1500000000, "collected_vnd": 1100000000, "order_count": 28},
    {"month": "2026-06", "revenue_vnd": 800000000,  "collected_vnd": 400000000,  "order_count": 15}
  ],
  "ytd_revenue_vnd": 8500000000,
  "ytd_collected_vnd": 7200000000
}
```

---

## 7. Storage

### POST `/storage/uploads/`

Multipart upload. Backend chuyển sang MinIO (nếu `MINIO_ENDPOINT` set) hoặc local.

```bash
curl -X POST http://localhost:8000/api/v1/storage/uploads/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@./image.jpg" \
  -F "purpose=ticket_photo"
# → 201 { "id": "...", "url": "/storage/serve/...", "size": 12345 }
```

### GET `/storage/serve/{id}/`

Serve file (presigned URL nếu MinIO).

---

## 8. Mã lỗi chuẩn

Tất cả endpoint trả lỗi theo shape:

```json
{
  "detail": "Thông điệp tiếng Việt cho người dùng cuối.",
  "code": "AUTH_INVALID",
  "fields": {"username": ["..."]}    // chỉ có khi 400 validation
}
```

| HTTP | code | Khi nào |
|---|---|---|
| 400 | `VALIDATION` | Payload sai shape (DRF ValidationError) |
| 401 | `AUTH_INVALID` | Sai mật khẩu |
| 401 | `AUTH_TOKEN_EXPIRED` | JWT hết hạn |
| 401 | `AUTH_TOKEN_INVALID` | JWT không decode được |
| 403 | `PERMISSION_DENIED` | Role không đủ quyền |
| 403 | `OWNERSHIP_DENIED` | Sale cố truy cập KH của sale khác |
| 404 | `NOT_FOUND` | Resource không tồn tại / đã soft-delete |
| 409 | `CONFLICT` | State conflict (vd convert quote chưa approved) |
| 429 | `RATE_LIMITED` | Brute-force lockout 5 lần / 15 phút |
| 500 | `SERVER_ERROR` | Lỗi backend (xem logs) |

---

## 9. Phân trang + filter + search

### Phân trang DRF

- Page size mặc định: 20 (cấu hình `REST_FRAMEWORK['PAGE_SIZE']`)
- Trả `{count, next, previous, results}`
- `?page=2` để lấy trang sau
- `next` / `previous` là URL hoàn chỉnh (FE chỉ cần follow)

### Filter

DRF dùng `django-filter`. Mỗi viewset khai `filterset_fields = [...]`.

```bash
# Tất cả param đều ?key=value, AND nhau
curl '/api/v1/crm/customers/?segment=steel&region=HCM&status=active'
```

### Search

`?search=<keyword>` áp dụng cho `search_fields` của viewset (thường là code/name).

### Ordering

`?ordering=field` (asc) hoặc `?ordering=-field` (desc). Nhiều field: `?ordering=-created_at,name`.

---

## 10. Test endpoint nhanh với httpie

```bash
pip install httpie

# Login + lưu token
http POST localhost:8000/api/v1/auth/login/ username=admin password=admin123 | tee /tmp/login.json
TOKEN=$(jq -r .access /tmp/login.json)

# Dùng token
http GET localhost:8000/api/v1/crm/customers/ Authorization:"Bearer $TOKEN"
http POST localhost:8000/api/v1/crm/quotes/ Authorization:"Bearer $TOKEN" \
  customer=<uuid> lines:='[{"part_no":"001005","qty":10,"unit_price_vnd":150000}]'
```

---

## 11. OpenAPI / Swagger

`drf-spectacular` đã cài. Khi dev server chạy:

```
http://localhost:8000/api/schema/        ← raw OpenAPI 3 JSON
http://localhost:8000/api/schema/swagger/ ← Swagger UI
http://localhost:8000/api/schema/redoc/   ← ReDoc UI
```

> **Lưu ý**: Schema này được sinh từ serializer + viewset. Khi thêm endpoint mới, schema tự cập nhật. FE có thể chạy `openapi-typescript` để gen types.
