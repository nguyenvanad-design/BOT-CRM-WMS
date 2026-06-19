# TOKINARC — V6.B.5 · Chat pipeline · Guardrail · Vòng học offline · DevOps

> ⚠️ **TÀI LIỆU LỖI THỜI (kiến trúc chatbot CŨ).** File này mô tả chatbot sidecar JWT + 27 tool gọi Django REST — KHÔNG còn dùng. Chatbot THẬT hiện tại là FastAPI v8.0 độc lập (X-API-Key + retrieval tự chứa, 11 tool in-process). Đọc `chatbot/README.md` và `docs/implementation/V6_MERGE_chatbot_real.md` để biết kiến trúc đúng. Giữ file này chỉ để tham khảo lịch sử thiết kế.


**Phần mới hoàn toàn của V6.B · gom mọi thứ sidecar/ML/ops mà V6.A thiếu**

Phụ thuộc: V6.B.1 (Topology), V6.B.2 (Models — app learning), V6.B.3 (chat contract)

Ngày soạn: 16/06/2026 · Phiên bản: 1.0

---

## Mục lục

1. Pipeline chat & Guardrail đầu vào (prompt-injection / PII)
2. Vòng học offline (queries.jsonl → Critic → Promotion → Golden Store → few-shot)
3. Confidence: cách tính tier + warnings
4. DevOps: secrets, backup/PITR, SSL, MinIO, health, logging

---

## 1. Pipeline chat & Guardrail đầu vào

### 1.1 Pipeline (theo sơ đồ B)

Mọi tin nhắn đi qua các tầng trong sidecar `main.py`:

```
Tin nhắn người dùng
   ↓
[1] Guardrail đầu vào   — prompt-injection · PII · chặn (§1.2)
   ↓
[2] Tiền xử lý          — chuẩn hóa tiếng Việt · gắn session
   ↓
[3] Cache               — FAQ regex · LLM cache TTL 5m (B.3 §4.4)
   ↓
[4] Planner LLM         — Gemini Pro · chọn tool + few-shot (từ Golden Store §2)
   ↓                          ┌─────────────────────────────┐
[5] Tool executor       ─────▶│ Retrieval: BM25+Vec+PQA     │
    11 tool · song song        │ (read-only Postgres)        │
    · timeout                   └──────────────┬──────────────┘
   ↓                                           ▼
[6] Responder LLM       — Gemini · tổng hợp → text tiếng Việt
   ↓                              ↓
[7] Confidence (§3)     ────────▶ SSE → khách (tier + warnings)
   ↓
[8] Query log           — ghi queries.jsonl + QueryLog (cho vòng học §2)
```

**Phân vai model**: Planner = Gemini **Pro** (cần reasoning chọn tool); Responder = Gemini (tổng hợp); Critic = Gemini **Flash** (rẻ, chạy batch §2).

**Tool executor**: 11 tool chạy **song song** (asyncio.gather) với **timeout** mỗi tool (mặc định 8s); tool nào timeout → bỏ qua, ghi warning. Tool **đọc** query Postgres trực tiếp; tool **ghi** gọi Django REST (B.1 §3) kèm JWT của user → Django enforce permission.

### 1.2 Guardrail đầu vào — `chatbot/guardrail.py` (MỚI)

Chạy **trước Planner**. Bắt buộc vì public gateway mở cho khách qua Zalo. Hai nhiệm vụ:

**(a) Prompt-injection detection**

```python
# chatbot/guardrail.py
import re

INJECTION_PATTERNS = [
    r"(?i)ignore (all |the )?(previous|above) instructions",
    r"(?i)bỏ qua (mọi |các )?(hướng dẫn|chỉ thị) (trước|trên)",
    r"(?i)you are now|bây giờ bạn là|act as (a |an )?(admin|developer|system)",
    r"(?i)reveal (your )?(system )?prompt|in ra (system )?prompt",
    r"(?i)\bDAN\b|jailbreak|chế độ nhà phát triển",
]

def detect_injection(text: str) -> bool:
    return any(re.search(p, text) for p in INJECTION_PATTERNS)
```

Phát hiện → **không** đưa vào Planner; trả 422 `GUARDRAIL_BLOCKED` với câu lịch sự ("Xin lỗi, mình chỉ hỗ trợ tư vấn sản phẩm hàn Tokinarc."). Ghi `QueryLog` với cờ blocked để review.

**(b) PII detection & masking**

Khách có thể dán số điện thoại, CMND, số tài khoản. Trước khi gửi LLM, **mask** PII trong prompt (không gửi raw ra Gemini), và **không** cache câu chứa PII:

```python
PII_PATTERNS = {
    "phone":  r"(0|\+84)\d{9,10}",
    "cccd":   r"\b\d{12}\b",
    "email":  r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "bank":   r"\b\d{9,16}\b",
}

def mask_pii(text: str) -> tuple[str, list[str]]:
    found = []
    out = text
    for kind, pat in PII_PATTERNS.items():
        if re.search(pat, out):
            found.append(kind)
            out = re.sub(pat, f"[{kind}]", out)
    return out, found     # gửi `out` cho LLM; `found` → set no_cache
```

**Output guardrail** (nhẹ): chặn Responder trả lời chứa giá của part `is_contact_price=True` (chỉ "vui lòng liên hệ"), và không bịa part-no không có trong catalog.

### 1.3 Phân quyền theo role trong chat

Sidecar đọc `role` từ JWT (B.1 §8):
- `role=customer` (khách Zalo/web): chỉ tool **đọc** (search_parts, check_compatibility, get_consumable_set, assembly_qa). **Cấm** tool ghi (create_quote_draft...) và tool xem dữ liệu nội bộ (tồn kho chi tiết, công nợ).
- `role in {sales, manager, ...}`: thêm tool ghi (qua Django REST) + tool nội bộ.

Bảng tool ↔ role nằm trong `core/tool_wrappers.py` (mở rộng từ V6 Mục 4C).

---

## 2. Vòng học offline

Mục tiêu: bot **tự cải thiện** từ log thật, không chặn người dùng (chạy cron). Pipeline đúng sơ đồ B:

```
queries.jsonl  →  Critic batch (Flash, /giờ)  →  Promotion gate (score≥4 · conf≥0.85)
                                                          ↓
        Planner  ◀──(few-shot, mũi tên đứt)──  Golden Store
```

### 2.1 Thu thập — `queries.jsonl` + bảng QueryLog

Sidecar tầng [8] ghi mỗi lượt: vừa append một dòng JSON vào `queries.jsonl` (rotate hằng ngày), vừa insert `learning_querylog` (B.2 §9) để query được bằng SQL. Trường quan trọng: `query_text`, `planner_tools`, `response_text`, `confidence`, `conf_tier`, `latency_ms`.

### 2.2 Critic batch — `manage.py run_critic_batch` (cron mỗi giờ)

Quét `QueryLog` chưa có `critic_score` trong giờ qua. Với mỗi log, gọi **Gemini Flash** chấm điểm 1–5 theo rubric (đúng tool? trả lời đủ? có bịa? đúng tương thích/giá?). Ghi `critic_score` + `critic_note`.

```python
# apps/learning/management/commands/run_critic_batch.py
RUBRIC = """Chấm 1-5 cho câu trả lời của trợ lý hàn Tokinarc.
5=chính xác, đúng tool, không bịa. 1=sai/bịa/lạc đề.
Trả JSON: {"score": int, "note": "..."}."""

def handle(self, *a, **k):
    logs = QueryLog.objects.filter(critic_score__isnull=True,
                                   ts__gte=now()-timedelta(hours=1))[:500]
    for lg in logs:
        res = flash_chat(RUBRIC, f"Q: {lg.query_text}\nA: {lg.response_text}")
        j = parse_json(res)
        lg.critic_score = j["score"]; lg.critic_note = j["note"]; lg.save()
```

### 2.3 Promotion gate — `manage.py promote_golden` (cron mỗi giờ, sau critic)

Chỉ log đạt **score ≥ 4 VÀ confidence ≥ 0.85** mới lên Golden Store:

```python
def handle(self, *a, **k):
    cand = QueryLog.objects.filter(promoted=False, critic_score__gte=4, confidence__gte=0.85)
    for lg in cand:
        GoldenExample.objects.create(
            source_log=lg, query_text=lg.query_text,
            ideal_tools=lg.planner_tools, ideal_answer=lg.response_text,
            score=lg.critic_score, confidence=lg.confidence, active=True)
        lg.promoted = True; lg.save()
```

Dedup: skip nếu đã có GoldenExample query gần trùng (so embedding hoặc hash chuẩn hóa) để Golden Store không phình.

### 2.4 Few-shot ngược về Planner (mũi tên đứt)

Khi build prompt cho Planner [4], sidecar **truy vấn Golden Store** lấy vài ví dụ liên quan nhất (theo embedding của query hiện tại, `active=True`) làm few-shot. Đây là vòng kín: log tốt → few-shot → Planner chọn tool chuẩn hơn.

```python
# core/golden_store.py (sidecar đọc qua Django REST hoặc Postgres read-only)
def few_shot_for(query: str, k: int = 3) -> list[dict]:
    # vector search trên GoldenExample.query_text embedding, active=True
    ...
```

> **An toàn**: Golden Store chỉ chứa ví dụ đã qua gate (người/critic duyệt). Có nút admin để `active=False` một ví dụ xấu lọt lưới. Không bao giờ học trực tiếp từ input khách chưa qua gate (tránh poisoning).

### 2.5 Lịch cron tổng hợp (nhắc lại từ B.1 §6)

```cron
30 * * * *  python manage.py run_critic_batch
45 * * * *  python manage.py promote_golden
```

---

## 3. Confidence: cách tính tier + warnings

Sidecar tổng hợp confidence từ tín hiệu pipeline (đã có sẵn `confidence_band` trong `main.py`):

| Tín hiệu | Ảnh hưởng |
| --- | --- |
| Retrieval score (BM25+Vec fuse cao) | ↑ |
| Tool trả kết quả khớp (vd part tồn tại, compatibility có edge) | ↑ |
| Có negative_rule chạm vào câu hỏi | ↓ + warning |
| Tool timeout / thiếu dữ liệu | ↓ + warning |
| Part `is_contact_price` | warning "giá liên hệ" |
| LLM tự báo không chắc | ↓ |

Map sang tier: `high ≥0.85`, `med 0.6–0.85`, `low <0.6` (B.3 §4.2). `warnings[]` là list string hiển thị cho người dùng. Trả trong event `done` của SSE.

---

## 4. DevOps

### 4.1 Secrets & env (fail-loud)

Liệt kê đầy đủ biến môi trường production (thiếu → process không khởi động):

```
# Django
DJANGO_SECRET_KEY=...
DJANGO_ALLOWED_HOSTS=app.tokinarc.vn
DJANGO_CORS_ORIGINS=https://app.tokinarc.vn
DJANGO_SETTINGS_MODULE=tokinarc.settings.production
# Database
PGHOST=postgres  PGPORT=5432  PGDATABASE=tokinarc  PGUSER=...  PGPASSWORD=...
# JWT RS256 (rotation 90 ngày + overlap 7 ngày)
JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private.pem
JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public.pem
JWT_KID=2026-06
# Redis (1 instance, tách logical DB)
REDIS_URL_CACHE=redis://redis:6379/0
REDIS_URL_RATELIMIT=redis://redis:6379/1
# MinIO (storage từ đầu)
MINIO_ENDPOINT=minio:9000  MINIO_ACCESS_KEY=...  MINIO_SECRET_KEY=...
MINIO_BUCKET=tokinarc  MINIO_SECURE=false
# Sidecar
GEMINI_API_KEY=...
DJANGO_JWKS_URL=http://django:8000/.well-known/jwks.json
DJANGO_REST_BASE=http://django:8000        # tool_clients gọi về
TOKINARC_ENV=production
```

Lưu secrets qua Docker secrets / file mount, **không** commit. JWT keypair sinh bằng `openssl genrsa`/`rsa -pubout`, mount read-only.

### 4.2 JWT key rotation (90 ngày + overlap 7 ngày)

- Sinh keypair mới với `kid` mới (vd `2026-09`).
- Trong 7 ngày overlap: JWKS endpoint trả **cả 2 public key**; Django ký bằng key mới nhưng vẫn verify token cũ. Sidecar cache JWKS, gặp `kid` lạ → re-fetch.
- Sau 7 ngày: gỡ key cũ khỏi JWKS. Token cũ (TTL access 15 phút, refresh 7 ngày) đã hết hạn tự nhiên.
- Quy trình thủ công định kỳ (90 ngày) hoặc script `manage.py rotate_jwt_key`.

### 4.3 Backup Postgres — pg_dump nightly + WAL (PITR)

```bash
# scripts/cron/backup.cron
# Logical dump hằng đêm 03:00 → MinIO bucket riêng 'tokinarc-backup'
0 3 * * *  pg_dump -Fc tokinarc | mc pipe backup/tokinarc-backup/dump_$(date +\%F).dump
```

WAL archiving cho PITR (postgresql.conf):
```
archive_mode = on
archive_command = 'mc pipe backup/tokinarc-backup/wal/%f < %p'
wal_level = replica
```
- **Test restore định kỳ** (hằng tháng) vào instance staging — backup không test = không có backup.
- Giữ dump 30 ngày, WAL 14 ngày. Bucket backup bật versioning + (lý tưởng) khác máy vật lý.

### 4.4 SSL — Let's Encrypt + Nginx

- `certbot` cấp cho `chat.tokinarc.vn` (public, HTTP-01 challenge bình thường) và `app.tokinarc.vn` (internal — bắt buộc **DNS-01 challenge** vì domain không expose ra Internet, không dùng HTTP-01 được).
- **VPN**: `app.tokinarc.vn` chỉ resolve và truy cập được trong **WireGuard self-host** (nếu công ty chưa có VPN doanh nghiệp). Split-horizon DNS: bản ghi A của `app.tokinarc.vn` trỏ IP nội bộ `10.0.0.10`, chỉ trả về cho client trong VPN.
- Auto-renew: `certbot renew` cron + reload nginx.
- Security headers (public gateway): HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, CSP cơ bản.

### 4.5 MinIO

- Service `minio` trong docker-compose; bucket `tokinarc` (file app) + `tokinarc-backup` (DB backup).
- Lifecycle: backup bucket auto-expire theo §4.3.
- `apps/storage/services.py` dùng client MinIO; presigned URL cho download nếu cần tránh proxy qua Django.

### 4.6 Health checks

| Endpoint | Auth | Ý nghĩa |
| --- | --- | --- |
| `GET /api/health/live/` | no | process sống → 200 |
| `GET /api/health/ready/` | no | DB + Redis + (sidecar) sẵn sàng → 200, else 503 |
| `GET /api/health/` | yes | chi tiết cho diagnostic |

Sidecar đã có sẵn `/api/v1/health/live|ready` (main.py v8.1.1). Django thêm tương ứng. LB/orchestrator probe `live` (restart) và `ready` (route traffic).

### 4.7 Logging & quan sát

- Log JSON structured ra stdout (gunicorn/uvicorn) → thu gom (Loki/CloudWatch/file).
- `request_id` xuyên suốt (middleware), trả trong lỗi 500 để tra.
- Sentry (optional) cho cả Django và sidecar.
- Metrics tối thiểu: latency chat p50/p95, tỉ lệ guardrail block, tỉ lệ confidence low, số GoldenExample tạo/ngày, dead-letter tồn đọng.

### 4.8 docker-compose — 8 service

```
postgres · redis · minio · django · chatbot · worker · nginx-public · nginx-internal
```
`worker` chạy cả 3 listener (B.1 §5) + cron (B.1 §6) — hoặc tách `worker` và `cron` thành 2 service nếu muốn rõ ràng. Django ×3 replica sau LB (sơ đồ B); sidecar 1–2 replica (lưu lượng thấp hơn).

---

## Checklist trước go-live

- [ ] 2 gateway tách biệt, public **không** chạm path nghiệp vụ (test thủ công từng path).
- [ ] Guardrail chặn được 5 mẫu injection + mask PII (unit test).
- [ ] JWT rotation thử nghiệm 1 lần trên staging (overlap hoạt động).
- [ ] Restore từ pg_dump + PITR thành công trên staging.
- [ ] LISTEN/NOTIFY: kill worker giữa chừng → event vào dead-letter → cron replay phục hồi.
- [ ] Vòng học: tạo log giả score 5/conf 0.9 → thấy lên Golden Store → Planner nhận few-shot.
- [ ] Multi-warehouse: thêm kho 2 → switcher hiện ra, API lọc đúng `?warehouse=`.
- [ ] Đo usage v5 chạy, báo cáo consumer còn gọi.
