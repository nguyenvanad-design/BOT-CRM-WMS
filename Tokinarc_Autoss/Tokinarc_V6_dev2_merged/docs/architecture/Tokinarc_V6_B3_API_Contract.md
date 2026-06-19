# TOKINARC — V6.B.3 · API contract

**REST FE↔Django · chat forward sang sidecar · confidence shape · hybrid retrieval · cache 2 tầng**

Phụ thuộc: V6.B.1 (Topology), V6.B.2 (Models)

Ngày soạn: 16/06/2026 · Phiên bản: 1.0

---

## Mục lục

1. Quy ước chung
2. Auth flow
3. Endpoint inventory theo app
4. Chat — forward sang FastAPI sidecar (confidence, retrieval, cache)
5. Error handling chuẩn
6. drf-spectacular & OpenAPI
7. CORS, rate-limit, versioning, đo usage v5

---

## 1. Quy ước chung

### 1.1 URL & versioning
- Endpoint nghiệp vụ: `/api/<app>/...` (vd `/api/crm/customers/`). Internal gateway expose.
- Chat: `/api/chat/...` (cả 2 gateway). Sidecar nội bộ giữ `/api/v2/...`, người dùng chỉ thấy `/api/chat/...`.
- Trailing slash bắt buộc (Django convention). FE client redirect-follow.

### 1.2 Auth
Mọi API cần `Authorization: Bearer <access>` trừ: `POST /api/auth/login/`, `POST /api/auth/refresh/`, `GET /api/health/live|ready/`, `GET /.well-known/jwks.json`.

JWT claims (Django phát, RS256):
```json
{ "sub":"user-uuid","username":"minh.t","role":"sales","customer_id":null,
  "iss":"tokinarc","aud":"tokinarc-api","exp":1718500000,"iat":1718496400 }
```
Access TTL 15 phút · Refresh TTL 7 ngày, rotation mỗi lần refresh.

### 1.3 Content type
- Request `application/json` UTF-8; multipart chỉ cho upload.
- Datetime ISO 8601 UTC; FE convert Asia/Ho_Chi_Minh.
- Money: integer VND. `"total_vnd": 185000000`.

### 1.4 Pagination
Page-based: `?page=2&page_size=20`, default 20, max 100. Dropdown dùng `/lookup/` compact.
```json
{ "count":47, "next":"...page=3", "previous":"...page=1", "results":[...] }
```

### 1.5 Filtering & sorting (django-filter)
```
GET /api/crm/customers/?segment=factory&region=HCM&ordering=-created_at
GET /api/wms/inventory/?warehouse=HCM&low_stock=true&zone=A
```
Search: `?search=keyword` full-text trên field quan trọng.

> **Multi-warehouse**: mọi endpoint WMS nhận `?warehouse=<code>`. Nếu bỏ trống và hệ thống chỉ 1 kho active → auto kho đó. FE ẩn switcher khi `warehouses.count===1`.

---

## 2. Auth flow

### 2.1 Login
```
POST /api/auth/login/   { "username":"minh.t", "password":"..." }
200: { "access":"...", "refresh":"...",
       "user":{ "id":"01J5...","username":"minh.t","full_name":"Trần Văn Minh",
                "role":"sales","email":"minh@tokinarc.vn","customer_id":null } }
401: { "detail":"Tài khoản hoặc mật khẩu không đúng", "code":"AUTH_INVALID" }
```

### 2.2 Refresh
```
POST /api/auth/refresh/   { "refresh":"..." }
200: { "access":"...", "refresh":"..." }   # rotate cả 2
```
Hết hạn / đã rotate → 401, FE về login.

### 2.3 Me / Logout
```
GET  /api/auth/me/       → 200 user object
POST /api/auth/logout/   { "refresh":"..." } → 204   # blacklist refresh
```
Access vẫn valid tới expire (15 phút) — tradeoff để không duy trì blacklist access.

### 2.4 JWKS (cho sidecar)
```
GET /.well-known/jwks.json   (no auth)
{ "keys":[ { "kty":"RSA","use":"sig","alg":"RS256","kid":"2026-06","n":"...","e":"AQAB" } ] }
```
Rotation 90 ngày + overlap 7 ngày: khi rotate, JWKS chứa **cả key cũ và mới** trong 7 ngày để token cũ vẫn verify. Sidecar cache, miss `kid` → re-fetch.

---

## 3. Endpoint inventory theo app

Liệt kê path + method + behavior; field do drf-spectacular sinh từ serializer.

### 3.1 accounts
| Method | Path | Role |
| --- | --- | --- |
| GET POST | /api/accounts/users/ | admin |
| GET PATCH | /api/accounts/users/{id}/ | admin / chính user |
| POST | /api/accounts/users/{id}/set-role/ | admin |
| GET | /api/accounts/audit-log/ | admin, manager |

### 3.2 catalog (đa số read-only)
| Method | Path | Mô tả |
| --- | --- | --- |
| GET | /api/catalog/parts/ | filter category, ecosystem, current_class |
| GET | /api/catalog/parts/{part_no}/ | chi tiết + compatible torches + **process + gas-flow** |
| GET | /api/catalog/parts/lookup/ | compact dropdown |
| GET | /api/catalog/parts/search/ | **hybrid search** (BM25+Vec), `?q=`, `?top_k=` |
| GET | /api/catalog/torches/ | list |
| GET | /api/catalog/torches/{model_code}/ | chi tiết + part mappings + **consumable sets** |
| GET | /api/catalog/compatibility/ | `?src=&edge_type=`, **đã lọc negative_rules** |
| GET | /api/catalog/consumable-sets/ | `?current_class=&ecosystem=` (upsell) |

`search/` chạy trong Django (ORM `CosineDistance` + BM25 rerank), **không** forward sang FastAPI (FE search độc lập với chat). Compatibility query **luôn áp negative_rules** (B.2 §3.2) để không trả cặp loại trừ.

### 3.3 crm
| Method | Path | Mô tả |
| --- | --- | --- |
| GET POST | /api/crm/customers/ | list/create |
| GET PATCH DELETE | /api/crm/customers/{id}/ | CRUD |
| GET | /api/crm/customers/{id}/360/ | gộp contacts, orders, debt, warranty, tickets |
| POST | /api/crm/customers/import/ | Excel/CSV |
| GET POST | /api/crm/contacts/ | CRUD |
| GET POST | /api/crm/leads/ | CRUD |
| POST | /api/crm/leads/{id}/qualify/ | → tạo Opportunity, link back; **publish LeadCreated** |
| POST | /api/crm/leads/{id}/reject/ | rejected + lý do |
| GET POST | /api/crm/opportunities/ | CRUD |
| POST | /api/crm/opportunities/{id}/move-stage/ | `{stage}` + audit |
| GET POST | /api/crm/quotes/ | CRUD (lines lồng body) |
| POST | /api/crm/quotes/{id}/approve/ | manager duyệt |
| POST | /api/crm/quotes/{id}/send/ | `send_email=true` option |
| POST | /api/crm/quotes/{id}/to-contract/ | (4B.4) → SalesOrder, copy lines |
| GET POST | /api/crm/visits/ | + photos (multipart → MinIO) |
| POST | /api/crm/visits/{id}/checkin/ | GPS check-in |
| GET POST | /api/crm/activities/ | call/zalo/email/meet |
| GET POST | /api/crm/tickets/ | CRUD |
| POST | /api/crm/tickets/{id}/assign/ · /resolve/ | gán kỹ sư · đóng |
| GET | /api/crm/warranty/ | filter sắp hết |
| GET | /api/crm/installed-machines/ | link customer + serial |

Quote payload:
```json
{ "customer":"01J5...","due_date":"2026-07-15","notes":"...",
  "lines":[ {"part":"002001","qty":50,"unit_price":45000,"discount_pct":5},
            {"torch":"TK-508RR","qty":5,"unit_price":12000000,"discount_pct":0} ] }
```
`total_vnd` BE tự tính, không nhận từ FE.

### 3.4 sales
| Method | Path | Mô tả |
| --- | --- | --- |
| GET POST | /api/sales/orders/ | list/create |
| GET PATCH DELETE | /api/sales/orders/{id}/ | CRUD |
| POST | /api/sales/orders/{id}/sign/ | draft→pending→active |
| POST | /api/sales/orders/{id}/ship/ | **publish OrderCreated** → WMS tạo Outbound |
| POST | /api/sales/orders/{id}/cancel/ | + lý do |
| GET POST | /api/sales/payments/ | ghi thanh toán |
| GET | /api/sales/debt-aging/ · /summary/ | từ mv_debt_aging |

### 3.5 wms
| Method | Path | Mô tả |
| --- | --- | --- |
| GET | /api/wms/warehouses/ | list (FE quyết switcher) |
| GET | /api/wms/zones/ · /bins/ | `?warehouse=` `?zone=` |
| GET | /api/wms/inventory/ | `?warehouse=&part=&zone=&low_stock=true` |
| GET | /api/wms/inventory/{part_no}/ | tồn across bins (lọc `?warehouse=`) |
| POST | /api/wms/inventory/adjust/ | `{bin,part,new_qty,reason}` |
| POST | /api/wms/inventory/transfer/ | nội bộ / liên kho |
| GET POST | /api/wms/asn/ | CRUD |
| POST | /api/wms/asn/{id}/arrive/ | → InboundOrder; **publish StockReceived** |
| GET POST | /api/wms/inbound/ | CRUD |
| POST | /api/wms/inbound/{id}/confirm/ · /putaway/ | nhận · gợi ý vị trí |
| GET POST | /api/wms/outbound/ | CRUD |
| GET | /api/wms/outbound/{id}/pick-list/ | FIFO/FEFO/Nearest |
| POST | /api/wms/outbound/{id}/pick-confirm/ · /ship/ | pick · giao + update Serial/InstalledMachine |
| GET | /api/wms/serials/ · /{sn}/ | filter status/torch · lịch sử |
| GET | /api/wms/lots/ | FEFO |
| GET | /api/wms/stock-movements/ | history |
| GET | /api/wms/scan/{code}/ | barcode → part/serial/lot |

### 3.6 analytics (chỉ đọc)
| Path | Nguồn |
| --- | --- |
| /api/analytics/kpi/overview/ | live + mv |
| /api/analytics/revenue/monthly\|by-product\|by-segment\|by-region/ | mv_monthly_revenue |
| /api/analytics/profit/waterfall/ · /cashflow/ · /cashflow/forecast/ | live |
| /api/analytics/debt-aging/ | mv_debt_aging |
| /api/analytics/customer-health/ | live |
| /api/analytics/installed-base/ | mv_installed_base (+ ConsumableSet forecast) |
| /api/analytics/service/sla/ · /inventory/value/ · /forecast/sales/ | live / mv |

Query chung: `?period=2026-06` hoặc `?from=&to=`. Mặc định tháng hiện tại.

### 3.7 storage
| Method | Path | Mô tả |
| --- | --- | --- |
| POST | /api/storage/upload/ | multipart: file, kind, related_kind, related_id → MinIO |
| GET | /api/storage/files/{id}/ · /download/ | metadata · stream |

```json
{ "id":"01J5...","filename":"visit_dongnai.jpg",
  "url":"/api/storage/files/01J5.../download/","size_bytes":248192,"sha256":"..." }
```

---

## 4. Chat — forward sang FastAPI sidecar

Django **không** xử lý chat. Nginx (cả 2 gateway) route `/api/chat/*` → FastAPI :8080.

| FE gọi | Nginx forward | Sidecar |
| --- | --- | --- |
| POST /api/chat/query | → /api/v2/query | pipeline đầy đủ |
| POST /api/chat/stream | → /api/v2/stream | SSE |
| WS /api/chat/ws | → /ws/query | WebSocket |
| DELETE /api/chat/session/{id} | → /api/v2/session/{id} | clear session |

### 4.1 SSE event shape

Stream gồm nhiều event; FE render dần và đọc confidence ở cuối:
```
data: {"type":"tool_start","tool":"search_parts"}
data: {"type":"tool_done","tool":"search_parts","ms":120}
data: {"type":"text","chunk":"Béc hàn N 350A tương thích là ..."}
data: {"type":"text","chunk":"..."}
data: {"type":"done","confidence":0.91,"tier":"high","warnings":[],
       "tools_called":["search_parts","check_compatibility"],"session_id":"..."}
```

### 4.2 Confidence (tier + warnings)

Sidecar trả về độ tin cậy để FE hiển thị (chi tiết tính toán ở B.5 §1):
| tier | ngưỡng | FE hiển thị |
| --- | --- | --- |
| high | conf ≥ 0.85 | bình thường |
| med | 0.6 ≤ conf < 0.85 | badge "cần kiểm tra lại" |
| low | conf < 0.6 | banner "thông tin chưa chắc chắn, hãy xác nhận với NV" |

`warnings[]` ví dụ: `["part 002099 giá liên hệ — không báo giá tự động", "tồn kho thấp"]`.

### 4.3 Retrieval — hybrid BM25 + Vector + PQA

Sidecar retrieval (đã có sẵn trong `core/`): kết hợp **BM25** (`bm25_reranker`), **vector** pgvector (`vector_index`), và **PQA** (`procedural_qa_retriever` cho câu hỏi quy trình). Kết quả fuse → đưa vào Planner. Tài liệu này chốt: endpoint `/api/catalog/parts/search/` của Django chỉ làm BM25+Vec (không PQA); PQA chỉ chạy trong luồng chat.

### 4.4 Cache 2 tầng

| Tầng | Cơ chế | TTL |
| --- | --- | --- |
| FAQ regex | match câu hỏi phổ biến → trả lời mẫu, bỏ qua LLM | tĩnh |
| LLM cache | hash (query normalized + role) → cache response | 5 phút |

Cache lưu ở Redis DB0. Chỉ cache câu **không** chứa dữ liệu cá nhân/giá liên hệ.

### 4.5 Nginx streaming

```nginx
location /api/chat/ {
    proxy_pass http://chatbot:8080/api/v2/;
    proxy_buffering off; proxy_cache off; proxy_read_timeout 300s;
    proxy_set_header Authorization $http_authorization;
}
location /ws/chat {
    proxy_pass http://chatbot:8080/ws/query;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";
    proxy_read_timeout 600s;
}
```

---

## 5. Error handling chuẩn

```json
{ "detail":"Mô tả ngắn", "code":"ERR_SOMETHING",
  "fields": { "due_date":["Hạn báo giá không được trong quá khứ"] } }
```
`fields` chỉ có khi 400.

| Code | HTTP | Nghĩa |
| --- | --- | --- |
| AUTH_INVALID | 401 | sai user/pass |
| AUTH_TOKEN_INVALID / _EXPIRED | 401 | JWT sai / cần refresh |
| AUTH_FORBIDDEN | 403 | không đủ role |
| NOT_FOUND | 404 | — |
| VALIDATION_FAILED | 400 | có `fields` |
| CONFLICT | 409 | trạng thái không cho action |
| RATE_LIMITED | 429 | quá rate |
| GUARDRAIL_BLOCKED | 422 | chat bị guardrail chặn (injection/PII) |
| INTERNAL | 500 | có request_id |

FE interceptor: 401 `AUTH_TOKEN_EXPIRED` → refresh + retry; khác → toast.

---

## 6. drf-spectacular & OpenAPI

```python
# tokinarc/urls.py
path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
path('api/docs/',   SpectacularSwaggerView.as_view(url_name='schema'), name='swagger'),
```
FE auto-gen TS types: `npx openapi-typescript http://localhost:8000/api/schema/ -o src/lib/api/schema.d.ts`. Swagger chỉ expose trên **internal gateway**.

---

## 7. CORS, rate-limit, versioning, đo usage v5

### 7.1 CORS
```python
CORS_ALLOWED_ORIGINS = os.environ['DJANGO_CORS_ORIGINS'].split(',')   # fail-loud
CORS_ALLOW_CREDENTIALS = True
```

### 7.2 Rate limit
DRF throttle (Redis DB1) — thêm rate chặt ở **public gateway** (Nginx `limit_req`, B.1 §1.3):
```python
'DEFAULT_THROTTLE_RATES': { 'user':'600/min', 'anon':'20/min' }
# AnalyticsThrottle = '60/min'; ChatAnonThrottle (public) = '30/min'
```

### 7.3 Versioning & đo usage v5
- Hiện chỉ v1 (path-based). Breaking change → mở `/api/v2/...`, v1 chạy song song 6 tháng.
- **Đo usage v5** (câu hỏi mở #6): middleware đếm hit `/api/v5/*` theo consumer (platform header / IP), ghi bảng `v5_usage`. Cron `measure_v5_usage` (B.1 §6) tổng hợp hằng ngày → biết khi nào không còn client gọi v5 thì tắt an toàn.
