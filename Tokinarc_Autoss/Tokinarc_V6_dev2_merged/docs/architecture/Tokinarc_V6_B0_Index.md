# TOKINARC — V6.B.0 · Index bộ tài liệu Phương án B

**Modular topology · Django BE + React FE + Postgres/pgvector · FastAPI chatbot sidecar · Postgres LISTEN/NOTIFY event bus**

> ⚠️ **Cập nhật sau merge**: phần CHATBOT trong các tài liệu B.x mô tả bản sidecar JWT + 27 tool (thiết kế cũ). Chatbot THẬT đang dùng là FastAPI v8.0 độc lập (X-API-Key, 11 tool in-process, retrieval tự chứa). Phần Django/CRM/WMS/CEO/event-bus vẫn đúng. Kiến trúc chatbot đúng: `chatbot/README.md` + `docs/implementation/V6_MERGE_chatbot_real.md`.

Ngày soạn: 16/06/2026 · Phiên bản: 1.0

---

## Tổng quan

Bộ tài liệu **V6.B** hiện thực kiến trúc theo **sơ đồ Hướng B** (`tokinarc_v6_detailed_huong_b_split_ingress.png`), nhưng chốt stack triển khai cụ thể:

- **DB**: PostgreSQL 16 + pgvector — source of truth, audit_log, embeddings, materialized views.
- **BE chính**: Django 5.0 + DRF — Auth / CRM / WMS / Analytics (các *service module*).
- **Chat**: FastAPI sidecar (giữ nguyên `main.py` v8.1.1 + `core/*`) — LLM Orchestrator.
- **FE**: React 18 + Vite + TS — 3 UI (CRM cam · WMS xanh · CEO vàng) port từ HTML demo.
- **Event bus**: Postgres **LISTEN/NOTIFY** (không dùng Celery cho event).
- **Scheduler**: **cron hệ thống → Django management command** (refresh MV, Critic batch).
- **Storage**: MinIO (S3-compatible) ngay từ đầu.
- **Redis**: 1 instance, tách logical DB — chỉ còn session / cache / rate-limit.

> **Khác biệt cốt lõi với V6.A:** V6.A là "Django chính + sidecar" route qua **một** Nginx theo path. V6.B giữ stack đó nhưng **tách hẳn 2 gateway** (public sau WAF / internal sau VPN, cấm route chéo), đổi event bus sang **LISTEN/NOTIFY**, và **bổ sung 2 hệ thống mới**: Guardrail đầu vào và Vòng học offline (Critic → Golden Store → few-shot).

---

## Bộ tài liệu gồm 6 file

| File | Nội dung | Đối tượng |
| --- | --- | --- |
| **B.0** (file này) | Index, sơ đồ, thứ tự đọc, các quyết định đã chốt | Tất cả |
| **B.1** Stack & Topology | 2 gateway, Django + sidecar, LISTEN/NOTIFY, network segmentation, monorepo | Tech lead, DevOps |
| **B.2** Database & Models | ~32 Django model + **bổ sung 5 nhóm catalog còn thiếu** (negative_rules, process_edges, gas_flow_edges, consumable_sets, vocab), MV, migration | BE dev, DBA |
| **B.3** API Contract | REST contract, chat forward sang sidecar, **confidence shape, hybrid retrieval, cache 2 tầng** | BE + FE dev, QA |
| **B.4** Frontend React | Vite + shadcn, cấu trúc, API client, chat widget confidence/warnings, port plan | FE dev |
| **B.5** Chat · Guardrail · Vòng học · DevOps | Pipeline chat chi tiết, Guardrail prompt-injection/PII, offline learning loop, backup/SSL/secrets/health | Tech lead, ML, DevOps |
| **LLD** Low-Level Design & Data Flow | ⭐ **Cập nhật theo code thật (V6.C-fix3)**. Sequence/state-machine cho CRM·WMS·CEO·Chatbot, bảng 27 tool, phân quyền 3 lớp. Ghi rõ chỗ B.5 đã lỗi thời (11→27 tool, REST thay vì query trực tiếp). | Tất cả dev |

> ⚠️ Khi LLD và B.1–B.5 mâu thuẫn: **LLD là nguồn đúng** (bám code hiện tại).
> B.1–B.5 là thiết kế gốc, một số phần đã thay đổi qua fix1/fix2/fix3.

---

## Thứ tự đọc

| Vai trò | Đọc theo thứ tự |
| --- | --- |
| Tech lead / Architect | B.0 → B.1 → B.5 → B.2 → B.3 → B.4 |
| Backend dev (nghiệp vụ) | B.1 → B.2 → B.3 |
| Backend dev (chat/ML) | B.1 §3 → B.5 toàn bộ |
| Frontend dev | B.1 §4 → B.3 → B.4 |
| DevOps | B.1 (§1, §5, §6) → B.5 (§4 DevOps) |
| QA | B.3 toàn bộ → B.5 §1 (guardrail test) |

---

## Sơ đồ kiến trúc (tóm tắt từ PNG)

```
 KHÁCH (public)                         NHÂN VIÊN (nội bộ)
 Chat UI·Zalo  Chat UI·web              CRM UI   WMS UI   CEO UI
      \         /                           \      |      /
   ┌──────────────────┐                  ┌──────────────────────┐
   │ PUBLIC GATEWAY   │  ✗ không route   │ INTERNAL GATEWAY      │
   │ chỉ /api/chat    │ ───chéo────────  │ /api/crm /wms /anal.  │
   │ /api/auth        │                  │ sau VPN · mạng nội bộ │
   │ TLS·WAF·rate lim │                  │ TLS                   │
   └────────┬─────────┘                  └───────────┬──────────┘
            │                                        │
            ▼                                        ▼
   ┌───────────────────────────────────────────────────────────┐
   │ DJANGO BACKEND (×3 replica sau LB · cùng image)             │
   │  Auth module · CRM module · WMS module · Analytics module   │
   │  (internal → role gate → service modules)                   │
   └───────────────┬───────────────────────────┬────────────────┘
                   │ chat forward                │
                   ▼                             │
   ┌───────────────────────────────┐            │
   │ FASTAPI SIDECAR · Chat module  │            │
   │  Guardrail → Tiền xử lý →      │            │
   │  Cache → Planner(Gemini Pro) → │            │
   │  Tool executor (11 tool ∥) →   │            │
   │  Responder(Gemini) → SSE       │            │
   │  Retrieval: BM25+Vec+PQA       │            │
   │  Confidence: tier + warnings   │            │
   │  Tool ghi → gọi Django REST    │            │
   └───────────────┬───────────────┘            │
                   ▼                             ▼
   ┌──────────────────────────┐   ┌──────────────────────────┐
   │ POSTGRES + pgvector      │   │ REDIS                    │
   │ source of truth·audit_log│   │ session·cache·rate-limit │
   │ embeddings·MV            │   └──────────────────────────┘
   └────────────┬─────────────┘
                │ LISTEN/NOTIFY
                ▼
   ┌──────────────────────────────────────────────┐
   │ EVENT BUS — Postgres LISTEN/NOTIFY            │
   │ LeadCreated · OrderCreated · StockReceived    │
   └───────┬───────────────┬───────────────┬───────┘
           ▼               ▼               ▼
   Embedding worker   Forecast worker   Analytics worker
   (cùng codebase Django · entry point riêng · ghi ngược về Postgres)

   ┌──────────────────────────────────────────────────────────┐
   │ VÒNG HỌC OFFLINE (cron · không chặn người dùng)           │
   │ queries.jsonl → Critic batch(Flash,/giờ) →                │
   │ Promotion gate(score≥4·conf≥0.85) → Golden Store →        │
   │ few-shot ──(mũi tên đứt)──▶ Planner                       │
   └──────────────────────────────────────────────────────────┘
```

---

## Quan hệ với V6 gốc & V6.A

- **V6 gốc** (`Tokinarc_Chuan_bi_Code_V6.docx` v1.1): vẫn là nguồn cho bối cảnh nghiệp vụ (Mục 1–4), phạm vi tool bot (Mục 4C), gộp Sales Orders (Mục 4B.4).
- **V6.A.*** (Django + 1 Nginx): **bị thay thế** bởi V6.B.*. Khác biệt chính: tách 2 gateway, LISTEN/NOTIFY thay Celery-event, thêm Guardrail + Vòng học.
- Các quyết định đã chốt (7 câu hỏi V6.A §0) **vẫn giữ**, trừ event bus (Celery → LISTEN/NOTIFY).

---

## Các quyết định đã chốt (carry-over + mới)

| # | Hạng mục | Quyết định |
| --- | --- | --- |
| 1 | JWT key rotation | 90 ngày + overlap 7 ngày (sidecar fetch JWKS mới) |
| 2 | Storage | MinIO (S3-compatible) **từ đầu** — `FileObject.backend` default `'s3'` |
| 3 | Redis | 1 instance, tách logical DB: DB0 cache/session, DB1 rate-limit. **Không** còn broker (event bus = LISTEN/NOTIFY) |
| 4 | Backup | pg_dump nightly + WAL archive (PITR) → bucket MinIO riêng |
| 5 | SSL | Let's Encrypt (certbot) + Nginx, auto-renew, HSTS |
| 6 | v5 API | Chưa tắt; thêm middleware **đo usage** `/api/v5/*` để biết khi nào audit xong |
| 7 | Đa kho | Multi-warehouse schema **từ đầu**; FE ẩn switcher khi `warehouses.count===1`, auto chọn HCM; API ghi WMS **luôn nhận `warehouse_id`** |
| 8 | Event bus | **Postgres LISTEN/NOTIFY** (đảo quyết định Celery cũ) |
| 9 | Scheduler | **cron hệ thống → `manage.py <cmd>`** (refresh MV, Critic batch) |
| 10 | Guardrail | Viết **đầy đủ** — prompt-injection + PII, chặn trước Planner |
| 11 | Vòng học offline | Viết **đầy đủ** — Critic batch → Promotion gate → Golden Store → few-shot |

---

## Sửa đổi & versioning tài liệu

- Đổi data model → cập nhật **B.2 + B.3** (serializer phụ thuộc model).
- Thêm endpoint → cập nhật **B.3** (+ B.4 nếu cần page).
- Đổi stack/topology/event bus → cập nhật **B.1** (+ B.5 nếu chạm ops).
- Đổi pipeline chat / guardrail / vòng học → cập nhật **B.5**.
- Mỗi cập nhật **bump version** và ghi vào header: `Phiên bản: x.y (sửa gì)`.

---

## Quyết định đã chốt (các câu hỏi mở trước đây)

1. **uuid7 lib**: chốt **`uuid6`** (`pip install uuid6`, dùng `uuid6.uuid7()`). Không dùng uuid4 tạm. Đã cập nhật B.2 §1.
2. **VPN internal gateway**: **WireGuard self-host** nếu công ty chưa có VPN doanh nghiệp; nếu đã có thì dùng VPN sẵn. Đã phản ánh ở B.1 §1.2 + B.5 §4.4.
3. **Domain**: **`app.tokinarc.vn`** (internal, chỉ resolve trong VPN) và **`chat.tokinarc.vn`** (public). **2 gateway riêng** — không dùng chung path `/app` + `/chat` vì đã xác định tách service lâu dài. Đã phản ánh ở B.1 §1 + B.5 §4.4.
