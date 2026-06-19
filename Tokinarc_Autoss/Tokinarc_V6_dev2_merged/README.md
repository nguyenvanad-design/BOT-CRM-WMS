# Tokinarc V6 — Hệ thống phân phối súng hàn

> **Phiên bản**: V6.C-fix3 (17/06/2026) — backend 71 test ✓, chatbot 6 smoke ✓, FE slice 1 (Login + Customers)
> **Kiến trúc**: Django backend (CRM/WMS/CEO) + chatbot FastAPI v8.0 độc lập + React FE + Postgres/pgvector + LISTEN/NOTIFY
> **Tài liệu dev**: bắt đầu từ [`docs/dev/DEV_SETUP.md`](docs/dev/DEV_SETUP.md)

---

## Tóm tắt 30 giây

Hệ thống nội bộ cho nhà phân phối súng hàn Tokinarc tại VN:

- **CRM**: Customer · Lead · Opportunity · Quote · Visit · Ticket
- **Sales**: SalesOrder (gộp đơn bán + hợp đồng khung) · Payment
- **WMS**: Warehouse/Zone/Bin · Inventory · SerialNumber · StockMovement · FIFO/FEFO/NEAREST
- **Catalog**: 837 Part · 121 Torch · 7541 compatibility edge (BGE-M3 embedding sẵn sàng wire)
- **Analytics**: CEO dashboard (revenue/debt aging/inventory value/pipeline forecast)
- **Chatbot**: FastAPI v8.0 độc lập, Gemini function-calling, 11 tool tra cứu catalog, retrieval FAISS+BM25+PQA, vision phụ tùng

Chatbot THẬT tự chứa data + index, auth bằng `X-API-Key`, **không** gọi Django. Backend Django (CRM/WMS/CEO) là service riêng. Hai bên chỉ gặp ở nginx. Chi tiết: [`chatbot/README.md`](chatbot/README.md).

---

## Bắt đầu từ đâu

| Bạn là ai | Đọc đầu tiên |
|---|---|
| Dev mới (cài máy + chạy local) | [`docs/dev/DEV_SETUP.md`](docs/dev/DEV_SETUP.md) |
| Dev backend (thêm endpoint / model) | [`EXTENDING.md`](EXTENDING.md) + [`docs/dev/API_REFERENCE.md`](docs/dev/API_REFERENCE.md) |
| Dev chatbot (setup / thêm tool) | [`chatbot/README.md`](chatbot/README.md) |
| Dev frontend (thêm page mới) | [`docs/dev/FRONTEND_GUIDE.md`](docs/dev/FRONTEND_GUIDE.md) |
| Hiểu data flow tổng thể | [`docs/architecture/Tokinarc_V6_LLD_DataFlow.md`](docs/architecture/Tokinarc_V6_LLD_DataFlow.md) |
| Gặp lỗi khi chạy | [`docs/dev/TROUBLESHOOTING.md`](docs/dev/TROUBLESHOOTING.md) |
| Thêm event/handler async | [`docs/dev/EVENTS_HANDLERS.md`](docs/dev/EVENTS_HANDLERS.md) |

---

## Cấu trúc thư mục

```
Tokinarc_V6/
├── README.md                    ← file này
├── EXTENDING.md                 ← quy ước mở rộng (mọi PR phải đọc Mục 8)
├── docs/
│   ├── architecture/            ← thiết kế gốc B0-B6 + LLD bám code
│   ├── implementation/          ← changelog từng đợt fix
│   └── dev/                     ← (mới) hướng dẫn dev hàng ngày
├── backend/                     ← Django, 7 app HTTP, 71 test ✓
│   ├── apps/
│   │   ├── accounts/            ← User + JWT + JWKS + roles.py (SINGLE SOURCE)
│   │   ├── catalog/             ← Part/Torch + pricing.py (SINGLE SOURCE)
│   │   ├── crm/                 ← Customer + Lead/Opp/Quote/Visit/Ticket
│   │   ├── sales/               ← SalesOrder + Payment (gộp hợp đồng + đơn bán)
│   │   ├── wms/                 ← Multi-warehouse + FIFO/FEFO + Serial
│   │   ├── analytics/           ← CEO dashboard (manager+ only)
│   │   ├── storage/             ← FileObject + MinIO
│   │   ├── learning/            ← QueryLog + Critic (worker only)
│   │   └── common/              ← BaseModel + AuditLog (tầng base)
│   └── tokinarc/
│       ├── settings/{base,dev,production,test}.py
│       ├── eventbus/channels.py  ← SINGLE SOURCE channel
│       └── urls.py
├── chatbot/                     ← FastAPI v8.0 (THẬT) — service độc lập
│   ├── main.py                  ← pipeline V2: input → vision → Gemini function-calling → retrieval
│   ├── core/                    ← retrieval engine (FAISS vector + BM25 + Procedural-QA), CER, orchestrator
│   ├── data/                    ← tokinarc_data_v19.json + procedural_qa_kb.jsonl + assembly/pricelist
│   ├── indexes/                 ← FAISS index (tokinarc_faiss.index, tokinarc_chunks.pkl, procedural_qa_idx/)
│   ├── vision_endpoint.py       ← route phân tích ảnh phụ tùng
│   ├── vision_chat.html         ← UI chat (serve ở '/')
│   ├── requirements.txt         ← fastapi + torch + sentence-transformers (bge-m3) + faiss
│   └── .env                     ← GEMINI_API_KEY + TOKINARC_API_KEY (X-API-Key auth)
│   # LƯU Ý: chatbot thật dùng X-API-Key (không phải JWT) và TỰ chứa data —
│   # KHÔNG gọi Django. CRM/WMS/CEO ở backend/ là service riêng. Hai bên độc lập,
│   # chỉ gặp nhau qua nginx (/api/chat → chatbot, /api/ → django).
├── frontend/                    ← React + Vite + Tailwind, slice 1
│   ├── src/
│   │   ├── App.tsx              ← BrowserRouter + Protected route
│   │   ├── components/Layout.tsx
│   │   ├── lib/
│   │   │   ├── api.ts           ← axios + auto-refresh + mutex
│   │   │   ├── auth/store.ts    ← zustand
│   │   │   └── types.ts         ← khớp 1-1 serializer backend
│   │   └── pages/{Login,Customers}.tsx
│   └── tailwind.config.js       ← theme thép + lửa hàn
├── infra/
│   ├── docker-compose.yml
│   ├── .env.example
│   ├── postgres/Dockerfile      ← postgres:16 + mc (WAL archive fix)
│   ├── nginx/{public,internal}.conf
│   └── scripts/{gen_keys,worker_entrypoint,backup}.sh
└── .github/workflows/ci.yml     ← lint + drift + role sync + pytest
```

---

## Trạng thái test (V6.C-fix3)

```bash
cd backend && pytest apps/ -q
# → 71 passed in ~10s
```

| App | Test | Cover gì |
|---|---|---|
| `accounts` | 6 | login/refresh/lockout/JWKS/role |
| `catalog` | 14 | list/retrieve/search ILIKE Part+Torch, alias OEM |
| `crm` | 27 | Customer CRUD + 360 · Lead convert · Opp move-stage · Quote create/approve/to-contract · ownership filter |
| `sales` | 5 | SalesOrder + Payment debt computation |
| `wms` | 10 | multi-warehouse + adjust/transfer |
| `analytics` | 4 | IsManagerOrAdmin enforce + aggregate query |
| `storage` | 3 | MinIO/local fallback |
| `learning` | 2 | QueryLog + Critic |
| **Tổng** | **71** | |

```bash
cd chatbot && python _smoke_test_orch.py
# → 6 passed
```

Chatbot tự chứa 11 tool tra cứu catalog, retrieval FAISS+BM25+PQA. Eval đầy đủ: `python run_eval.py` (xem `chatbot/README.md` §8).

```bash
cd frontend && npm run build
# → typecheck 0 lỗi, vite build ~5s, dist 322 KB JS (gzip 107 KB)
```

---

## Setup nhanh

**Local dev (SQLite, không cần Docker)** — xem [`docs/dev/DEV_SETUP.md`](docs/dev/DEV_SETUP.md):

```bash
# Backend
cd backend && pip install -r requirements-dev.txt
python manage.py migrate && python manage.py runserver

# Chatbot
cd chatbot && pip install -r requirements.txt
uvicorn main:app --reload --port 8080

# Frontend
cd frontend && npm install && npm run dev
```

**Production (Docker)**:

```bash
bash infra/scripts/gen_keys.sh
cp infra/.env.example .env  # sửa secret keys
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose exec django python manage.py migrate
docker compose exec django python manage.py seed_users_roles --admin-password=<strong>
docker compose exec django python manage.py seed_from_json data/tokinarc_data_v19.json
```

---

## 5 nguyên tắc bất di bất dịch

Đọc kỹ trước khi viết code mới. Vi phạm = vỡ kiến trúc.

### 1. Django là single source of truth cho dữ liệu

Chatbot thật KHÔNG gọi Django (khác thiết kế sidecar cũ). Nó tự chứa data + FAISS index, dùng `X-API-Key`. Backend Django (CRM/WMS/CEO) enforce permission riêng cho các API nghiệp vụ. Chi tiết: `chatbot/README.md` + `docs/implementation/V6_MERGE_chatbot_real.md`.

### 2. Role single source = `apps/accounts/roles.py`

Đổi role / quyền → **chỉ sửa file này**. Sinh lại file cho chatbot + FE:
```bash
python manage.py dump_roles --format=py --out ../chatbot/roles_generated.py
python manage.py dump_roles --format=ts --out ../frontend/src/lib/auth/roles.ts
```
CI sẽ exit 1 nếu quên (xem [`docs/dev/TROUBLESHOOTING.md`](docs/dev/TROUBLESHOOTING.md) §3).

### 3. Pricing single source = `apps/catalog/pricing.py`

Không tự `obj.price_vnd * qty * (1 - discount)`. Dùng `compute_line_total()` hoặc `get_effective_price()`. Khi thêm logic giá mới (PriceList theo segment, voucher...), thêm vào file này, không phân tán.

### 4. Bất kỳ thay đổi model → chạy `makemigrations --check`

Drift migration (do quên đặt tên index) đã từng vỡ `catalog.PartEmbedding`. CI block tự động — xem [`EXTENDING.md`](EXTENDING.md) §2 + §8.

### 5. Phân quyền — backend là tầng chặn thật

| Phần | Cơ chế |
|---|---|
| API nghiệp vụ (CRM/WMS/CEO) | Django permission theo role: `IsManagerOrAdmin`, `WmsAccess`, `SalesPermission`... |
| Single-source role | `backend/apps/accounts/roles.py` |
| Chatbot | `X-API-Key` (service-level). Catalog đọc public cho khách. |

> Lưu ý: mô hình "3 lớp guardrail chatbot" của thiết kế sidecar cũ KHÔNG còn áp
> dụng — chatbot thật không phân role nội bộ. Phân quyền role nằm ở backend Django.

---

## Roadmap (sau fix3)

| Slice | Trạng thái | Mô tả |
|---|---|---|
| Backend CRM/WMS/Sales/Analytics | ✅ xong | 71 test pass, drift = 0 |
| Chatbot Gemini wire | ✅ xong | bật/tắt theo key, stub mode dev |
| FE Slice 1 (Login + Customers) | ✅ xong | typecheck 0, build sạch |
| FE Slice 2 (Quotes) | ⏳ tiếp | Backend ready, FE cần thêm CRUD form |
| FE Slice 3 (Chat widget) | ⏳ | gọi `/chatbot/api/v2/query` |
| FE Slice 4 (CEO dashboard) | ⏳ | manager+ only, recharts |
| Event handlers thật | ⏳ | `apps/<app>/handlers.py` + `apps.ready()` |
| Materialized Views | ⏳ | `RunSQL CREATE MV` migration |
| Vector search BGE-M3 | ⏳ | `seed_embeddings.py` + pgvector cosine |
| WebSocket `/ws/query` | ⏳ | port từ V5, streaming response |

---

## Liên hệ + đóng góp

PR mới phải đi qua [`EXTENDING.md`](EXTENDING.md) §8 (4 lệnh check). Bẫy đã biết: [`EXTENDING.md`](EXTENDING.md) §9.
