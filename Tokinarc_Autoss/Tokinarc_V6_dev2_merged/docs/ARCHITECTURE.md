# Tokinarc V6 — Kiến trúc hệ thống

> ERP cho AUTOSS (phân phối súng hàn): Frontend React + Backend Django + Chatbot FastAPI + PostgreSQL/pgvector.
> 65 bảng · 161 endpoint chức năng · 13 Django app · 8 vai trò.

---

## 1. Kiến trúc tổng thể (runtime — các service & cổng)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              NGƯỜI DÙNG (trình duyệt)                          │
│              Nhân viên nội bộ  ·  Khách hàng (Zalo/web chatbot)                │
└───────────────────────────┬──────────────────────────────┬───────────────────┘
                            │ HTTPS                          │ HTTPS
                            ▼                                ▼
┌───────────────────────────────────────────┐   ┌─────────────────────────────┐
│  FRONTEND  (React + Vite + TypeScript)    │   │  CHATBOT KHÁCH (FastAPI)    │
│  :5173 (dev) / :8443 (prod)               │   │  :4000                      │
│  • zustand (auth) · react-query           │   │  • bge-m3 + FAISS (RAG)     │
│  • react-router · react-hook-form         │   │  • Gemini (LLM)             │
│  • 5 tab: CRM·WMS·Dịch vụ·CEO·Quản trị    │   │  • tra cứu SP, bắt lead     │
│  • zxing-wasm (quét mã)                   │   └──────────────┬──────────────┘
└───────────────────┬───────────────────────┘                  │ ghi lead
                    │ REST /api/v1 (JWT)                         │ (lead-intake key)
                    ▼                                            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  BACKEND  (Django 5 + DRF + SimpleJWT)        :8000 (dev) / :5905 (prod)       │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │ 13 Django apps (161 endpoint chức năng)                                   │ │
│  │  accounts · crm · sales · purchasing · catalog · wms ·                    │ │
│  │  analytics · common · learning · storage                                  │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│  • roles.py = nguồn phân quyền duy nhất  • settings: base/dev/test/prod        │
│  • AI nội bộ (analytics/assistant.py → gọi thẳng Gemini)                       │
└──────┬──────────────────────────┬─────────────────────────────┬───────────────┘
       │ ORM                       │ HTTPS                        │ export
       ▼                           ▼                              ▼
┌──────────────────────┐   ┌─────────────────┐         ┌────────────────────┐
│ PostgreSQL+pgvector  │   │ Gemini API      │         │ MISA · Excel/Word  │
│ Docker tokinarc-db   │   │ (Google, ngoài) │         │ (hóa đơn, chứng từ)│
│ :5433  · 65 bảng     │   │ tóm tắt/intent  │         │ openpyxl/python-docx│
└──────────────────────┘   └─────────────────┘         └────────────────────┘
```

---

## 2. Backend — 13 Django app (theo lớp)

```
┌─ NỀN TẢNG ───────────────────────────────────────────────────────────────┐
│  accounts   User + Role (8 vai trò) + JWT + phân quyền (roles.py)         │
│  common     Notification · AuditLog · Excel/Word/letterhead · pagination  │
│  storage    File (ghi âm, recap, ảnh)                                      │
└──────────────────────────────────────────────────────────────────────────┘
┌─ DANH MỤC ───────────────────────────────────────────────────────────────┐
│  catalog    Part (838) · Torch (122) · cost_vnd (WAC) · PartEmbedding     │
└──────────────────────────────────────────────────────────────────────────┘
┌─ NGHIỆP VỤ CRM ──────────────────────────────────────────────────────────┐
│  crm        Lead · Customer · Contact · Opportunity · Quote · Contract ·  │
│             Visit · Activity · Ticket                                      │
│  sales      SalesOrder · Invoice · Payment · ReturnOrder                   │
└──────────────────────────────────────────────────────────────────────────┘
┌─ NGHIỆP VỤ KHO ──────────────────────────────────────────────────────────┐
│  wms        Warehouse·Zone·Bin · InventoryItem · Serial · Lot ·           │
│             StockMovement · Inbound · Outbound · CycleCount · ASN         │
│  purchasing PurchaseOrder · Supplier · Payment  (+ WAC khi nhận hàng)     │
└──────────────────────────────────────────────────────────────────────────┘
┌─ PHÂN TÍCH / AI ─────────────────────────────────────────────────────────┐
│  analytics  KPI · Doanh thu · Forecast · Hiệu suất sale · AI Summary ·    │
│             assistant.py (intent + tóm tắt, gọi Gemini)                    │
│  learning   QueryLog · GoldenExample · EventDeadLetter (cho AI)           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Frontend — cấu trúc theo tab/module

```
src/
├── components/Layout.tsx ─── MODULES (5 tab) + NAV theo role + cô lập tab
├── lib/
│   ├── auth/store.ts ─────── zustand: user/JWT + isManager/isWmsControl/isAdmin
│   ├── api.ts ─────────────── axios + interceptor JWT
│   └── list.ts ────────────── fetchPage/fetchAll/fetchCount (phân trang)
└── pages/
    ├── crm/      Dashboard(tab) · Customers(+Contacts) · Leads(+Sources) ·
    │             Opportunities · Pipeline · Quotes · Orders · Contracts ·
    │             Invoices · Receivables · Tickets · Visits · Products
    ├── wms/      Inventory(+lowstock) · Trace(Serial+Lô) · Movements ·
    │             Inbound · Outbound · Scan(zxing-wasm) · CycleCount ·
    │             Warehouses(quản lý kho) · WarehouseMap · KPI
    ├── purchasing/  PurchaseOrders · Suppliers
    ├── ceo/      Overview · Revenue · Debt · Forecast · AISummary · Approvals
    └── admin/    Users (quản trị)
```

---

## 4. Luồng xử lý 1 request (request lifecycle)

```
Browser ──(1) JWT Bearer──▶ DRF View
                              │ (2) Permission: roles.py kiểm tra vai trò
                              │ (3) get_queryset: lọc ownership (sale↔manager)
                              │ (4) Serializer: validate + (ẩn giá vốn nếu ko phải manager)
                              ▼
                          ORM ──▶ PostgreSQL
                              │ (5) side-effect: notify() + AuditLog
                              ▼
                          Response JSON ──▶ react-query cache ──▶ UI
```

---

## 5. Tech stack

| Lớp | Công nghệ |
|---|---|
| **Frontend** | React 18 · Vite · TypeScript · zustand · @tanstack/react-query · react-router · react-hook-form · Tailwind · zxing-wasm |
| **Backend** | Django 5.0 · DRF · SimpleJWT · django-filter · openpyxl · python-docx |
| **Chatbot** | FastAPI · sentence-transformers (bge-m3) · FAISS · Gemini |
| **AI nội bộ** | Gemini API (gọi thẳng từ Django) |
| **Database** | PostgreSQL + pgvector · Docker (tokinarc-db:5433) |
| **Auth** | JWT (access/refresh) · JWKS · role-based (8 vai trò) |
| **Test** | pytest (SQLite in-memory) · 172 tests |

---

## 6. Môi trường & triển khai

```
DEV (local)                          PROD (server 14.224.210.210)
├ FE  :5173  (vite dev)              ├ FE  :8443  (build tĩnh)
├ BE  :8000  (runserver)             ├ BE  :5905  (gunicorn/uvicorn)
├ Bot :4000                          ├ Bot :4000
└ DB  Docker :5433                   └ DB  :5433
   settings.dev (Postgres)              settings.production
   settings.test (SQLite, pytest)
```

---

## 7. Phân quyền (8 vai trò)

| Vai trò | Tab | Quyền chính |
|---|---|---|
| customer | — | Chỉ chatbot (không vào hệ thống nội bộ) |
| sales | CRM | Bán hàng của mình; báo giá CK≤5% tự duyệt |
| manager | CRM | + Duyệt CK≤10% · Dashboard toàn team · giá vốn/lãi gộp |
| warehouse | WMS | Tồn·Nhập·Xuất·Quét·Kiểm kê (không mua hàng/sửa cấu trúc) |
| wh_manager | WMS | + Mua hàng·NCC·Điều chỉnh·Kho&vị trí·duyệt kiểm kê |
| service | Dịch vụ | Ticket·Bảo hành |
| ceo | CEO | Duyệt cấp 2 · báo cáo · AI Summary |
| admin | Tất cả | Quản trị user & phân quyền |

---

## 8. Số liệu hệ thống

| Hạng mục | Số |
|---|---|
| Bảng DB | 65 (59 nghiệp vụ + 6 hệ thống) |
| Model | 61 |
| Endpoint chức năng | ~161 (296 URL pattern gồm biến thể format) |
| Django app | 13 |
| Vai trò | 8 |
| Test | 172 (pytest, SQLite) |

---

## 9. Nguyên tắc kiến trúc

1. **roles.py = nguồn phân quyền duy nhất** — backend ép, frontend chỉ ẩn/hiện UI.
2. **Ownership filtering** ở `get_queryset` — sale thấy của mình, manager thấy hết.
3. **AI nội bộ tách khỏi chatbot khách** — cùng dùng Gemini nhưng độc lập.
4. **Mọi biến động có AuditLog + Notification** — truy vết & thông báo.
5. **Settings tách 4 lớp** (base/dev/test/prod) — test dùng SQLite, không đụng DB thật.

---

*Tài liệu sinh tự động — Tokinarc V6. Cập nhật khi kiến trúc thay đổi.*
