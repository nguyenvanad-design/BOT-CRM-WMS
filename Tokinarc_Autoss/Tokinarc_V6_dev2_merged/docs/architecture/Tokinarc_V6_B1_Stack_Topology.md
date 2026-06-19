# TOKINARC — V6.B.1 · Stack & Topology

> ⚠️ **TÀI LIỆU LỖI THỜI (kiến trúc chatbot CŨ).** File này mô tả chatbot sidecar JWT + 27 tool gọi Django REST — KHÔNG còn dùng. Chatbot THẬT hiện tại là FastAPI v8.0 độc lập (X-API-Key + retrieval tự chứa, 11 tool in-process). Đọc `chatbot/README.md` và `docs/implementation/V6_MERGE_chatbot_real.md` để biết kiến trúc đúng. Giữ file này chỉ để tham khảo lịch sử thiết kế.


**Phương án B: 2 gateway tách biệt · Django BE + FastAPI chat sidecar · Postgres LISTEN/NOTIFY event bus**

Phụ thuộc: V6.B.0 (Index) · V6 gốc v1.1

Ngày soạn: 16/06/2026 · Phiên bản: 1.0

---

## Mục lục

1. Network topology — 2 gateway tách biệt
2. Stack chi tiết — phiên bản & lý do
3. Ranh giới Django ↔ FastAPI chatbot
4. Cấu trúc monorepo
5. Event bus — Postgres LISTEN/NOTIFY + workers
6. Scheduler — cron → management command
7. Settings split & WSGI/ASGI
8. Auth bridge giữa Django và FastAPI
9. Lộ trình implement

---

## 1. Network topology — 2 gateway tách biệt

Đây là điểm khác biệt lớn nhất so với V6.A. Sơ đồ Hướng B tách **hai đường vào hoàn toàn độc lập**, không route chéo.

### 1.1 Public gateway (đường khách)

- **Ai đi qua**: Chat UI · Zalo, Chat UI · web (khách hàng, không đăng nhập nội bộ).
- **Chỉ mở**: `/api/chat/*` và `/api/auth/*`. Mọi path khác (`/api/crm`, `/api/wms`, `/api/analytics`, `/api/accounts`) → **404/403 ngay tại gateway**, không tới được backend.
- **Bảo vệ**: TLS (Let's Encrypt) · WAF (ModSecurity hoặc Cloudflare) · rate limit chặt (xem B.5 §1).
- **Domain đề xuất**: `chat.tokinarc.vn`.

### 1.2 Internal gateway (đường nhân viên)

- **Ai đi qua**: CRM UI, WMS UI, CEO UI (nhân viên).
- **Mở**: `/api/crm/*`, `/api/wms/*`, `/api/analytics/*`, `/api/accounts/*`, `/api/sales/*`, `/api/storage/*`, và cả `/api/chat/*` (nhân viên cũng chat được).
- **Bảo vệ**: TLS · **chỉ truy cập được từ mạng nội bộ / sau VPN**. Không expose ra Internet.
- **Domain đề xuất**: `app.tokinarc.vn` (chỉ resolve trong VPN, hoặc split-horizon DNS).

### 1.3 Quy tắc cấm route chéo

```
Public gateway   ──✗──>  /api/crm, /api/wms, /api/analytics   (CHẶN)
Internal gateway ──✓──>  tất cả
```

Hiện thực: **hai server block Nginx riêng** (có thể 2 container nginx, hoặc 2 `server {}` listen khác cổng/khác interface).

```nginx
# ── PUBLIC gateway (chat.tokinarc.vn :443, expose Internet) ──
server {
    listen 443 ssl;
    server_name chat.tokinarc.vn;
    ssl_certificate     /etc/letsencrypt/live/chat.tokinarc.vn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/chat.tokinarc.vn/privkey.pem;

    # CHỈ cho 2 nhóm path; mọi thứ khác bị chặn
    location /api/chat/ {
        limit_req zone=chat burst=10 nodelay;
        proxy_pass http://chatbot:8080/api/v2/;
        proxy_buffering off; proxy_cache off; proxy_read_timeout 300s;
        proxy_set_header Authorization $http_authorization;
    }
    location /api/auth/ {
        limit_req zone=auth burst=5 nodelay;
        proxy_pass http://django:8000;
    }
    location / { return 403; }          # chặn mọi path nghiệp vụ
}

# ── INTERNAL gateway (app.tokinarc.vn :443, chỉ trong VPN) ──
server {
    listen 10.0.0.10:443 ssl;          # bind vào interface nội bộ
    server_name app.tokinarc.vn;
    # ... ssl ...

    location /api/chat/ { proxy_pass http://chatbot:8080/api/v2/; proxy_buffering off; proxy_read_timeout 300s; }
    location /ws/chat   { proxy_pass http://chatbot:8080/ws/query; proxy_http_version 1.1;
                          proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }
    location /api/      { proxy_pass http://django:8000; }
    location /          { root /var/www/frontend; try_files $uri $uri/ /index.html; }
}
```

> **Hệ quả cho sidecar**: FastAPI nhận traffic từ **cả hai** gateway. Nó phải tự phân biệt role trong JWT — khách (`role=customer`) chỉ được gọi tool đọc; nhân viên được nhiều hơn (xem §3 và B.5 §1).

---

## 2. Stack chi tiết — phiên bản & lý do

| Lớp | Công nghệ | Phiên bản | Lý do |
| --- | --- | --- | --- |
| OS container | Ubuntu | 24.04 LTS | Khớp môi trường dev |
| Python | CPython | 3.11/3.12 | asyncio + FAISS ổn; tránh 3.13 |
| Django | Django | 5.0 LTS | LTS, async view đủ dùng |
| DRF | djangorestframework | 3.15+ | API chính cho FE |
| JWT | djangorestframework-simplejwt | 5.3+ | phát/verify + rotation refresh |
| Postgres | PostgreSQL | 16 | pgvector tốt, partial index, **LISTEN/NOTIFY** |
| pgvector | pgvector + pgvector-python | mới nhất | thay FAISS file |
| Cache/session | Redis | 7 | session · cache · rate-limit (DB0/DB1) |
| FastAPI sidecar | giữ `main.py` | v8.1.1+ | chỉ thêm auth bridge JWKS |
| LLM | Gemini (Pro/Flash) | qua API | Planner=Pro · Responder=Gemini · Critic=Flash |
| FE build | Vite | 5.x | build nhanh, không cần SSR |
| FE | React + TS | 18 / 5.x | LTS, typesafe |
| FE state | TanStack Query + Zustand | latest | server + client state |
| FE UI | shadcn/ui + Tailwind | latest | match dark theme demo |
| FE chart | Recharts | 2.x | dashboard CEO |
| Storage | MinIO | latest | S3-compatible self-host, từ đầu |
| Web server | gunicorn (Django) + uvicorn (FastAPI) | latest | WSGI + ASGI |
| Reverse proxy | Nginx | 1.26 | 2 gateway + serve FE static |
| WAF | ModSecurity / Cloudflare | — | chỉ trên public gateway |

> **Không dùng Celery.** Event bus = LISTEN/NOTIFY (§5). Task định kỳ = cron + management command (§6). Lý do: bỏ một broker + một hệ thống worker queue lớn, khớp tinh thần tối giản của sơ đồ B. Trade-off: mất retry/backoff sẵn có của Celery — bù bằng cách worker tự ghi trạng thái + cron quét lại job lỗi (xem §5.3).

---

## 3. Ranh giới Django ↔ FastAPI chatbot

**Nguyên tắc: Django là single source of truth cho dữ liệu và quyền. FastAPI không ghi DB trực tiếp.**

| Việc | Ai làm |
| --- | --- |
| CRUD customer/lead/quote/order/inventory | Django REST |
| Auth (login, refresh, /me, JWKS) | Django |
| User & role store | Django |
| Materialized views CEO dashboard | Django (cron refresh) |
| File/ảnh upload | Django (apps/storage → MinIO) |
| LLM function-calling pipeline | FastAPI (`main.py`) |
| Guardrail đầu vào (injection/PII) | FastAPI (xem B.5 §1) |
| Vision image analysis | FastAPI (`vision_module`) |
| Retrieval BM25 + Vector + PQA | FastAPI đọc Postgres trực tiếp (read-only) |
| Streaming SSE / WebSocket | FastAPI |
| **Tool LLM ghi dữ liệu** | FastAPI → **gọi Django REST với JWT của user** → Django enforce permission |
| Query log + vòng học offline | FastAPI ghi `queries.jsonl`; cron Django chạy Critic (B.5 §2) |

Ví dụ luồng (sale dùng bot soạn báo giá nháp):

```
React FE  ──login──▶ Django /api/auth/login ──▶ {access, refresh}
React FE  ──chat───▶ Internal GW /api/chat/stream ──▶ FastAPI /api/v2/stream
                     (Authorization: Bearer <access>)
FastAPI: verify JWT (JWKS của Django) → Guardrail → Planner chọn tool create_quote_draft
tool_client HTTP ──▶ Django POST /api/crm/quotes/ (Bearer <access>)
Django: check role=sales + ownership → insert → 201
FastAPI: nhận response → Responder tổng hợp → stream text về FE
```

**Hệ quả**: tool ghi trong FastAPI là **HTTP client gọi Django** (`core/tool_clients.py` — mới), không phải in-process function. Tool đọc (vector search, parts lookup) vẫn query Postgres trực tiếp vì rẻ và an toàn (read-only).

---

## 4. Cấu trúc monorepo

```
tokinarc/
├── README.md
├── docker-compose.yml          # 8 service: postgres, redis, minio, django,
│                               #   chatbot, worker, nginx-public, nginx-internal
├── nginx/
│   ├── public.conf             # public gateway (§1.3)
│   └── internal.conf           # internal gateway (§1.3)
├── scripts/
│   ├── run_migrations.sh
│   ├── dev_up.sh
│   └── cron/                   # crontab fragments (§6)
│
├── backend/                    # Django project
│   ├── manage.py
│   ├── requirements.txt
│   ├── tokinarc/
│   │   ├── settings/{base,dev,production}.py
│   │   ├── urls.py
│   │   ├── asgi.py  wsgi.py
│   │   └── eventbus/           # NEW: LISTEN/NOTIFY helpers (§5)
│   │       ├── publisher.py    # pg_notify wrapper
│   │       └── listener.py     # worker entry: LISTEN loop
│   ├── apps/
│   │   ├── accounts/           # User, role, audit_log, jwks
│   │   ├── catalog/            # parts, torches, edges, embeddings + 5 nhóm bổ sung (B.2)
│   │   ├── crm/
│   │   ├── sales/
│   │   ├── wms/
│   │   ├── analytics/          # MV + KPI endpoints + refresh command
│   │   ├── storage/            # MinIO wrapper
│   │   ├── learning/           # NEW: query log, critic, golden store (B.5 §2)
│   │   └── common/             # BaseModel, AuditMixin, utils
│   ├── workers/                # NEW: entry point riêng, cùng codebase
│   │   ├── embedding_worker.py
│   │   ├── forecast_worker.py
│   │   └── analytics_worker.py
│   └── management_commands/    # (trong apps/*/management/commands/)
│       # refresh_mv, run_critic_batch, promote_golden, measure_v5_usage
│
├── chatbot/                    # FastAPI sidecar — main.py hiện tại
│   ├── main.py                 # v8.1.1 (+ auth_bridge, + guardrail hook)
│   ├── core/                   # cer, vector_index, vision, orchestrator_v2,
│   │                           #   bm25_reranker, procedural_qa_retriever,
│   │                           #   tool_wrappers, session_store, query_logger ...
│   ├── auth_bridge.py          # NEW: verify Django JWT qua JWKS (§8)
│   ├── tool_clients.py         # NEW: HTTP client → Django REST
│   ├── guardrail.py            # NEW: prompt-injection + PII (B.5 §1)
│   ├── data/                   # tokinarc_data_v19.json (read-only)
│   └── requirements.txt
│
├── frontend/                   # React (xem B.4)
│   └── src/...
│
└── docs/
    └── Tokinarc_V6_B*.md
```

Lý do monorepo: 3 codebase nhỏ + cần đồng bộ migration + 1 team. Tách repo khi team tách.

---

## 5. Event bus — Postgres LISTEN/NOTIFY + workers

### 5.1 Vì sao LISTEN/NOTIFY (theo sơ đồ B)

Postgres có sẵn pub/sub: `NOTIFY channel, 'payload'` + `LISTEN channel`. Không cần broker ngoài. Đủ cho 3 sự kiện domain: `LeadCreated`, `OrderCreated`, `StockReceived`.

### 5.2 Publish — sau khi commit

Publish trong cùng transaction với thao tác ghi để **chỉ fire khi DB đã commit** (tránh event "ma"):

```python
# backend/tokinarc/eventbus/publisher.py
from django.db import connection, transaction
import json

def publish(channel: str, payload: dict):
    """Gọi trong transaction. NOTIFY chỉ thực sự gửi khi COMMIT thành công."""
    def _do():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_notify(%s, %s)", [channel, json.dumps(payload)])
    transaction.on_commit(_do)   # đảm bảo chỉ notify sau commit
```

Ví dụ trong viewset:

```python
# apps/sales/views.py
from tokinarc.eventbus.publisher import publish

@transaction.atomic
def perform_create(self, serializer):
    order = serializer.save(created_by=self.request.user)
    publish("OrderCreated", {"order_id": str(order.id), "customer_id": str(order.customer_id)})
```

### 5.3 Listen — worker

Mỗi worker là **process riêng, cùng codebase Django** (load Django setup rồi LISTEN):

```python
# backend/workers/analytics_worker.py
import os, django, select, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tokinarc.settings.production")
django.setup()

from django.db import connection
from apps.analytics.services import on_order_created

CHANNELS = ["OrderCreated", "StockReceived"]

def main():
    conn = connection.connection            # raw psycopg connection
    conn.set_isolation_level(0)             # autocommit cho LISTEN
    cur = conn.cursor()
    for ch in CHANNELS:
        cur.execute(f"LISTEN {ch};")
    while True:
        if select.select([conn], [], [], 30) == ([], [], []):
            continue                         # timeout 30s → loop (cho phép graceful stop)
        conn.poll()
        while conn.notifies:
            n = conn.notifies.pop(0)
            payload = json.loads(n.payload)
            try:
                handle(n.channel, payload)
            except Exception:
                log_failed(n.channel, payload)   # ghi bảng dead_letter để cron retry
```

| Worker | LISTEN channel | Việc |
| --- | --- | --- |
| embedding_worker | (gọi nội bộ khi part đổi) | cập nhật pgvector embedding |
| forecast_worker | LeadCreated, OrderCreated | lead score, demand forecast |
| analytics_worker | OrderCreated, StockReceived | aggregation, alerts |

### 5.4 Bù cho việc thiếu retry của Celery

- Worker bắt exception → ghi vào bảng `eventbus_dead_letter(channel, payload, error, ts)`.
- Cron mỗi 10 phút chạy `manage.py replay_dead_letter` để xử lý lại.
- NOTIFY **không bền** (mất nếu không có listener lúc fire). Vì vậy các event quan trọng (OrderCreated) **cũng** được worker quét bù qua bảng trạng thái (`order.analytics_processed=false`) — không chỉ dựa vào NOTIFY.

---

## 6. Scheduler — cron → management command

Không dùng Celery beat. Dùng **cron hệ thống** (trong container `worker` hoặc host) gọi management command. Mỗi job một dòng, log rõ.

```cron
# scripts/cron/tokinarc.cron
# Refresh materialized views — hàng giờ
0 * * * *   cd /app && python manage.py refresh_mv --group=hourly  >> /var/log/tokinarc/mv.log 2>&1
# MV nặng — mỗi ngày 02:00
0 2 * * *   cd /app && python manage.py refresh_mv --group=daily   >> /var/log/tokinarc/mv.log 2>&1
# Critic batch (vòng học) — hàng giờ
30 * * * *  cd /app && python manage.py run_critic_batch           >> /var/log/tokinarc/critic.log 2>&1
# Promotion gate — hàng giờ, sau critic
45 * * * *  cd /app && python manage.py promote_golden             >> /var/log/tokinarc/golden.log 2>&1
# Replay dead-letter events — mỗi 10 phút
*/10 * * * * cd /app && python manage.py replay_dead_letter        >> /var/log/tokinarc/dlq.log 2>&1
# Đo usage v5 (để biết khi nào tắt được) — mỗi ngày
0 1 * * *   cd /app && python manage.py measure_v5_usage           >> /var/log/tokinarc/v5.log 2>&1
```

Trade-off ghi rõ: cron không có dependency graph hay backfill như Airflow — chấp nhận vì khối lượng job nhỏ và đều. Nếu sau này job phụ thuộc nhau phức tạp, cân nhắc chuyển sang một orchestrator nhẹ.

---

## 7. Settings split & WSGI/ASGI

Chia `base.py` / `dev.py` / `production.py`. Production fail-loud nếu thiếu env.

```python
# settings/base.py (trích)
INSTALLED_APPS = [
    'django.contrib.auth', 'django.contrib.contenttypes',
    'rest_framework', 'rest_framework_simplejwt', 'corsheaders', 'drf_spectacular',
    'apps.accounts', 'apps.catalog', 'apps.crm', 'apps.sales',
    'apps.wms', 'apps.analytics', 'apps.storage', 'apps.learning', 'apps.common',
]
AUTH_USER_MODEL = 'accounts.User'
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework_simplejwt.authentication.JWTAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}
```

```python
# settings/production.py (trích)
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']                       # fail-loud
ALLOWED_HOSTS = os.environ['DJANGO_ALLOWED_HOSTS'].split(',')
CORS_ALLOWED_ORIGINS = os.environ['DJANGO_CORS_ORIGINS'].split(',')
# JWT RS256 keypair path (gắn rotation 90 ngày — B.5 §4)
SIMPLE_JWT = {'ALGORITHM': 'RS256',
              'SIGNING_KEY': open(os.environ['JWT_PRIVATE_KEY_PATH']).read(),
              'VERIFYING_KEY': open(os.environ['JWT_PUBLIC_KEY_PATH']).read(),
              'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
              'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
              'ROTATE_REFRESH_TOKENS': True, 'BLACKLIST_AFTER_ROTATION': True,
              'ISSUER': 'tokinarc', 'AUDIENCE': 'tokinarc-api'}
```

**WSGI + gunicorn** cho Django (Channels nằm ở sidecar nên không cần ASGI):

```
gunicorn tokinarc.wsgi:application --workers 3 --threads 4 \
  --worker-class gthread --bind 0.0.0.0:8000 --access-logfile - --error-logfile -
```

FastAPI giữ uvicorn (port 8080).

---

## 8. Auth bridge giữa Django và FastAPI

Django ký JWT bằng **RS256** (private key), expose `/.well-known/jwks.json` (public key). FastAPI fetch JWKS lúc start, verify chữ ký. Đúng least-privilege: sidecar compromise cũng không tự phát được JWT giả.

```python
# chatbot/auth_bridge.py
import os, jwt, httpx
from functools import lru_cache
from fastapi import Header, HTTPException

DJANGO_JWKS_URL = os.getenv("DJANGO_JWKS_URL", "http://django:8000/.well-known/jwks.json")
DJANGO_ISSUER   = os.getenv("DJANGO_JWT_ISSUER", "tokinarc")

@lru_cache(maxsize=1)
def _get_jwks():                       # cache; TTL refresh khi kid đổi (rotation 90 ngày)
    return httpx.get(DJANGO_JWKS_URL, timeout=5).json()

def verify_jwt(token: str) -> dict:
    jwks = _get_jwks()
    hdr = jwt.get_unverified_header(token)
    key = next(k for k in jwks["keys"] if k["kid"] == hdr["kid"])
    pub = jwt.algorithms.RSAAlgorithm.from_jwk(key)
    return jwt.decode(token, pub, algorithms=["RS256"],
                      issuer=DJANGO_ISSUER, audience="tokinarc-api")

async def verify_jwt_dep(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    try:
        return verify_jwt(authorization[7:])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid token: {e}")
```

Thay `verify_api_key` hiện tại trong `main.py` bằng `Depends(verify_jwt_dep)`. `user_ctx` (chứa `role`, `customer_id`) truyền xuống orchestrator để guardrail + tool biết "ai gọi". Khi rotate key, Django bump `kid`; sidecar miss cache → re-fetch JWKS. Overlap 7 ngày để key cũ vẫn verify được trong lúc client còn token cũ.

---

## 9. Lộ trình implement

| Giai đoạn | Nội dung | Khối lượng |
| --- | --- | --- |
| 1. Auth + 2 gateway | Django project, accounts app, RS256 + JWKS; auth_bridge.py vào sidecar; dựng 2 nginx (public/internal) | 1–1.5 tuần |
| 2. Tầng dữ liệu | Migration Django; apps/catalog (port JSON v19 + **5 nhóm bổ sung**); vector_index → pgvector | 1.5–2 tuần |
| 3. API nghiệp vụ | apps/crm + sales + wms + analytics; serializer + viewset; drf-spectacular | 2–3 tuần |
| 3C. Tool bot | `tool_clients.py` trong sidecar gọi Django REST; mọi tool ghi đi qua đây | 1 tuần |
| 4. Event bus + workers | eventbus publisher/listener; 3 worker process; dead-letter + cron replay | 1 tuần |
| 5. Guardrail | `guardrail.py` (injection + PII) trước Planner | 0.5 tuần |
| 6. Vòng học offline | apps/learning (query log, critic, golden store) + 2 management command + cron | 1–1.5 tuần |
| 7. Frontend React | Vite + shadcn; port CRM → WMS → CEO; chat widget | 3–4 tuần (song song GĐ 3) |
| 8. DevOps | MinIO, backup PITR, SSL certbot, secrets, health, logging | 1 tuần (song song) |

Tổng ~10–13 tuần với 1 BE + 1 FE + hỗ trợ DevOps. **Bắt đầu: Giai đoạn 1** (backbone cho tất cả).
