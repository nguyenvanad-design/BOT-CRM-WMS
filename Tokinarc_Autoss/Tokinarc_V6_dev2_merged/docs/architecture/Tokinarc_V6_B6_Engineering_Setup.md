# TOKINARC — V6.B.6 · Engineering Setup

**Dependency pin · docker-compose · auth security · seed script · test strategy · CI/CD · logging · backup · security checklist · FE perf budget · i18n**

Phụ thuộc: V6.B.1–B.5

Ngày soạn: 16/06/2026 · Phiên bản: 1.0

> File này gom toàn bộ phần "vận hành kỹ thuật" còn thiếu. Các artifact chạy được (requirements.txt, package.json, docker-compose.yml, seed_from_json.py, ci.yml, backup.sh) được xuất kèm thành file riêng — phần dưới giải thích + trích nội dung chính.

---

## Mục lục

1. Dependencies — backend, sidecar, frontend
2. docker-compose & Dockerfile
3. Auth security detail (password policy, lockout, login rate limit)
4. Seed script — `seed_from_json.py` chi tiết
5. Test strategy — pytest + factory_boy + Playwright
6. CI/CD — GitHub Actions
7. Logging & monitoring — Sentry + structured log
8. Database backup — pg_dump + WAL script cụ thể
9. Security checklist
10. Frontend performance budget
11. i18n strategy (i18n-ready, chưa dịch EN)

---

## 1. Dependencies

Pin version để build reproducible. 3 file riêng (xem artifact kèm).

**`backend/requirements.txt`** (Django + DRF + workers + learning + storage):
```
Django==5.0.6
djangorestframework==3.15.1
djangorestframework-simplejwt==5.3.1
django-cors-headers==4.3.1
django-filter==24.2
drf-spectacular==0.27.2
psycopg[binary]==3.1.19          # psycopg3 — hỗ trợ LISTEN/NOTIFY tốt
pgvector==0.3.0
gunicorn==22.0.0
redis==5.0.4
minio==7.2.7
uuid6==2024.1.12                 # sinh UUID7 (đã chốt B.2 §1)
cryptography==42.0.7             # RS256 JWT keypair
sentry-sdk==2.3.1
python-dotenv==1.0.1
openpyxl==3.1.2                  # import Excel KH
# dev/test (tách requirements-dev.txt)
```

**`backend/requirements-dev.txt`**:
```
-r requirements.txt
pytest==8.2.1
pytest-django==4.8.0
pytest-cov==5.0.0
factory-boy==3.3.0
faker==25.3.0
ruff==0.4.7
mypy==1.10.0
```

**`chatbot/requirements.txt`** (sidecar — giữ stack hiện tại + auth bridge):
```
fastapi==0.111.0
uvicorn[standard]==0.30.1
pydantic==2.7.3
httpx==0.27.0
PyJWT[crypto]==2.8.0             # verify RS256 từ JWKS
google-genai==0.3.0             # Gemini Pro/Flash
python-dotenv==1.0.1
rank-bm25==0.2.2                # BM25 reranker
numpy==1.26.4
sentry-sdk==2.3.1
# (FAISS/embedding deps giữ theo môi trường hiện tại của core/)
```

**`frontend/package.json`** — xem artifact; các dep chính pin theo B.4 §1, thêm `i18next`, `react-i18next` (§11), `@playwright/test` (§5).

---

## 2. docker-compose & Dockerfile

`docker-compose.yml` — 8 service (xem artifact đầy đủ). Tóm tắt:

| Service | Image/Build | Port | Ghi chú |
| --- | --- | --- | --- |
| postgres | postgres:16 | 5432 (nội bộ) | volume data + `archive_command` cho PITR |
| redis | redis:7 | 6379 (nội bộ) | DB0 cache, DB1 rate-limit |
| minio | minio/minio | 9000/9001 | bucket tokinarc + tokinarc-backup |
| django | build backend/ | 8000 (nội bộ) | gunicorn ×3 worker |
| chatbot | build chatbot/ | 8080 (nội bộ) | uvicorn sidecar |
| worker | build backend/ | — | LISTEN/NOTIFY + cron |
| nginx-public | nginx:1.26 | 443 (Internet) | chỉ /api/chat + /api/auth |
| nginx-internal | nginx:1.26 | 443 (VPN 10.0.0.10) | toàn bộ |

Healthcheck mỗi service; `depends_on` với `condition: service_healthy`. `worker` chạy `cron` + listener (entrypoint script khởi cả hai).

---

## 3. Auth security detail

Bổ sung cho B.1 §8 / B.3 §2 — những phần trước chưa cụ thể.

### 3.1 Password policy
Dùng Django `AUTH_PASSWORD_VALIDATORS` + custom:
```python
AUTH_PASSWORD_VALIDATORS = [
  {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
   'OPTIONS': {'min_length': 10}},
  {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
  {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
  {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
]
```
Tối thiểu 10 ký tự, không phổ biến, không toàn số, không giống username/email.

### 3.2 Account lockout
Sau **5 lần login sai** trong 15 phút → khóa tài khoản 15 phút. Lưu đếm ở Redis DB1:
```python
# apps/accounts/services.py
KEY = "login_fail:{username}"
def record_fail(username):
    n = redis_rl.incr(KEY.format(username=username))
    if n == 1: redis_rl.expire(KEY.format(username=username), 900)   # 15m window
    return n
def is_locked(username) -> bool:
    return int(redis_rl.get(KEY.format(username=username)) or 0) >= 5
def clear_fail(username):
    redis_rl.delete(KEY.format(username=username))
```
Login view: nếu `is_locked` → 429 `RATE_LIMITED` ("Tài khoản tạm khóa, thử lại sau 15 phút"). Login thành công → `clear_fail`. Lockout theo **username + IP** để tránh một IP dò nhiều account.

### 3.3 Login rate limit
- Tầng Nginx public gateway: `limit_req zone=auth burst=5 nodelay` (B.1 §1.3).
- Tầng DRF: `AnonRateThrottle` scope riêng cho `/auth/login/` = `10/min` per IP.

### 3.4 Token & session
- Access 15m, refresh 7d, rotation + blacklist sau rotation (B.1 §7).
- Refresh token lưu FE ở localStorage; access in-memory (B.4 §3). Cân nhắc httpOnly cookie cho refresh nếu cần chống XSS mạnh hơn (ghi chú: đổi thì sửa interceptor).
- Logout blacklist refresh.

---

## 4. Seed script — `seed_from_json.py` chi tiết

Management command nạp đủ **12 nhóm** JSON v19 đúng thứ tự FK, idempotent (chạy lại không nhân đôi). Xem artifact đầy đủ; logic chính:

```python
# apps/catalog/management/commands/seed_from_json.py
class Command(BaseCommand):
    help = "Seed catalog từ tokinarc_data_v19.json (12 nhóm)"

    def add_arguments(self, p):
        p.add_argument('json_path')
        p.add_argument('--truncate', action='store_true', help='Xóa catalog trước khi seed')

    @transaction.atomic
    def handle(self, json_path, truncate=False, **k):
        data = json.load(open(json_path, encoding='utf-8'))
        if truncate: self._truncate()
        # Thứ tự BẮT BUỘC theo FK:
        self._seed_torches(data['torches'])                       # 1
        self._seed_parts(data['parts'])                           # 2
        self._seed_compat(data['compatibility_edges'])            # 3 (FK part/torch)
        self._seed_tpm(data['torch_part_mappings'])               # 4
        self._seed_process(data['process_edges'])                 # 5
        self._seed_gasflow(data['gas_flow_edges'])                # 6
        self._seed_consumable(data['consumable_sets'])            # 7 (+ items)
        self._seed_negative(data['negative_rules'])               # 8
        self._seed_vocab(data['category_vocabulary'])             # 9
        self._seed_aliases(data['fake_pno_aliases'])              # 10
        # torch_model_index (11) → chỉ validate, không seed
        self._validate(data)
        self.stdout.write(self.style.SUCCESS(f"Seed xong: {len(data['parts'])} parts, "
                          f"{len(data['torches'])} torches"))

    def _seed_parts(self, rows):
        objs = [Part(tokin_part_no=r['tokin_part_no'], category=r['category'],
                     ecosystem=r.get('ecosystem',''), ...) for r in rows]
        Part.objects.bulk_create(objs, update_conflicts=True,
            update_fields=[...], unique_fields=['tokin_part_no'])   # upsert → idempotent

    def _seed_consumable(self, sets):
        for s in sets:
            cs, _ = ConsumableSet.objects.update_or_create(
                set_id=s['set_id'], defaults={...})
            for item in s.get('items', []):
                ConsumableSetItem.objects.update_or_create(
                    consumable_set=cs, part_id=item['part'], role=item.get('role',''),
                    defaults={'qty': item.get('qty', 1)})

    def _validate(self, data):
        # mọi from_part trong process_edges phải tồn tại; cảnh báo orphan
        ...
```

`update_conflicts=True` (Django 5 bulk upsert) làm seed **idempotent** — chạy lại an toàn khi JSON cập nhật. Embeddings tách riêng (`seed_embeddings`) vì gọi BGE-M3 chậm.

---

## 5. Test strategy — pytest + factory_boy + Playwright

### 5.1 Pyramid
- **Unit (nhiều nhất)**: serializer validation, money/aging logic, guardrail regex, confidence calc, seed parser.
- **Integration**: viewset + DB thật (test Postgres), permission theo role, event publish (LISTEN/NOTIFY mock), tool_clients → Django REST.
- **E2E (ít, quan trọng)**: Playwright 3 flow (B.4 §8) — login→BG→HĐ; nhập→xuất kho; CEO KPI.

### 5.2 Backend — pytest + pytest-django + factory_boy
```python
# conftest.py
import pytest
@pytest.fixture
def api(db):
    from rest_framework.test import APIClient
    return APIClient()

# factories.py
import factory
from apps.crm.models import Customer
class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta: model = Customer
    code = factory.Sequence(lambda n: f"KH-{n:04d}")
    name = factory.Faker('company', locale='vi_VN')
    segment = 'factory'
    owner = factory.SubFactory('tests.factories.UserFactory')

# test_quote.py
def test_quote_total_auto_computed(api, sales_user):
    api.force_authenticate(sales_user)
    r = api.post('/api/crm/quotes/', {...lines...}, format='json')
    assert r.status_code == 201
    assert r.data['total_vnd'] == 2362500   # BE tính, FE không gửi
```
- Test DB: dùng Postgres thật (pgvector cần extension) — `pytest --reuse-db`.
- Coverage gate: `pytest-cov`, fail nếu < 70% ở app nghiệp vụ.

### 5.3 Sidecar — pytest async
Test guardrail (injection/PII mask), tool timeout, confidence tier. Mock Gemini bằng fixture trả response cố định.

### 5.4 E2E — Playwright
```ts
// e2e/quote-to-contract.spec.ts
test('sale tạo BG rồi chuyển HĐ', async ({ page }) => {
  await login(page, 'sales1', '...');
  await page.goto('/crm/quotes');
  await page.click('text=Tạo báo giá');
  // ... điền form, submit, approve, to-contract
  await expect(page.locator('text=Đã chuyển HĐ')).toBeVisible();
});
```
Chạy trên CI với service Postgres + Django + sidecar (compose test). Headless Chromium.

---

## 6. CI/CD — GitHub Actions

Repo trên GitHub. Workflow `.github/workflows/ci.yml` (xem artifact). 4 job:

1. **lint** — ruff (BE), eslint + tsc (FE).
2. **test-backend** — service Postgres 16 (+ pgvector) + Redis; `pytest --cov`.
3. **test-frontend** — `npm ci`, `tsc --noEmit`, `npm run build`, Playwright E2E (compose test).
4. **build-images** (chỉ trên `main`/tag) — build 3 image (django/chatbot/frontend), push GitHub Container Registry, tag theo SHA.

Deploy: thủ công/staging trước (workflow_dispatch), production sau khi smoke test. Secrets qua GitHub Environments (DB, Gemini, MinIO key — không hardcode).

---

## 7. Logging & monitoring

### 7.1 Structured log (JSON ra stdout)
```python
# settings/production.py
LOGGING = {
  'version': 1, 'disable_existing_loggers': False,
  'formatters': {'json': {'()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
    'format': '%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s'}},
  'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'json'}},
  'root': {'handlers': ['console'], 'level': 'INFO'},
}
```
Middleware gắn `request_id` (uuid) vào mọi log + trả trong header `X-Request-ID` và body lỗi 500. Sidecar dùng `python-json-logger` tương tự.

### 7.2 Sentry
```python
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
sentry_sdk.init(dsn=os.environ['SENTRY_DSN'], integrations=[DjangoIntegration()],
                traces_sample_rate=0.1, send_default_pii=False, environment='production')
```
`send_default_pii=False` (quan trọng — khách gửi PII qua chat). Sidecar init Sentry riêng (FastAPI integration). FE: `@sentry/react` với `tracesSampleRate` thấp.

### 7.3 Metrics tối thiểu (theo B.5 §4.7)
Chat latency p50/p95, tỉ lệ guardrail block, tỉ lệ confidence low, GoldenExample/ngày, dead-letter tồn đọng, login fail rate. Expose `/metrics` (prometheus-client) nếu có Prometheus; nếu không, log số liệu hằng giờ qua cron.

---

## 8. Database backup — script cụ thể

`scripts/backup.sh` (gọi bởi cron B.1 §6) — xem artifact. Tóm tắt:
```bash
#!/usr/bin/env bash
set -euo pipefail
TS=$(date +%F_%H%M)
# 1. Logical dump (custom format, nén)
pg_dump -Fc -h "$PGHOST" -U "$PGUSER" "$PGDATABASE" \
  | mc pipe "backup/tokinarc-backup/dump/tokinarc_${TS}.dump"
# 2. Dọn dump > 30 ngày
mc rm --recursive --force --older-than 30d "backup/tokinarc-backup/dump/" || true
echo "OK backup $TS"
```
WAL archiving (postgresql.conf) cho PITR — đã ghi B.5 §4.3. **Test restore hằng tháng** vào staging: `pg_restore` + replay WAL tới thời điểm bất kỳ. Backup không test = không có backup.

---

## 9. Security checklist

Gom mọi điểm bảo mật rải rác thành một nơi để QA/lead tick:

**Network & gateway**
- [ ] Public gateway chỉ mở `/api/chat` + `/api/auth`; mọi path nghiệp vụ → 403 (test từng path).
- [ ] Internal gateway chỉ truy cập qua WireGuard; không expose Internet.
- [ ] TLS cả 2 domain; HSTS + security headers ở public.

**Auth**
- [ ] Password policy ≥10 ký tự (§3.1).
- [ ] Account lockout 5 lần/15 phút (§3.2).
- [ ] Login rate limit Nginx + DRF (§3.3).
- [ ] JWT RS256, rotation 90 ngày + overlap 7 ngày; private key mount read-only.
- [ ] Refresh rotation + blacklist; logout thu hồi refresh.

**App**
- [ ] DRF `IsAuthenticated` mặc định; object-level filter theo owner.
- [ ] Guardrail injection + PII mask (B.5 §1); chat khách chỉ tool đọc.
- [ ] Money `total_vnd` BE tính, không nhận từ FE.
- [ ] CORS fail-loud (whitelist origin), không `*`.
- [ ] Upload: kiểm mime + size limit; không trust filename; lưu MinIO key random.
- [ ] SQL injection: chỉ ORM/param query (raw SQL của MV không nhận input user).

**Data & secrets**
- [ ] Secrets qua env/Docker secrets, không commit; `.env` trong `.gitignore`.
- [ ] Sentry `send_default_pii=False`.
- [ ] Backup mã hóa at-rest (MinIO SSE) + versioning.
- [ ] Audit log append-only cho mọi hành động ghi.

**Vận hành**
- [ ] Dependency scan (Dependabot trên GitHub).
- [ ] Image scan (trivy trong CI — optional).

---

## 10. Frontend performance budget

| Chỉ số | Target | Cách đo |
| --- | --- | --- |
| Initial JS bundle (gz) | < 300 KB (route /login + shell) | Vite build report |
| Tổng JS (gz) lazy-loaded | < 800 KB | rollup-plugin-visualizer |
| LCP | < 2.5s (4G, máy tầm trung) | Lighthouse CI |
| CLS | < 0.1 | Lighthouse |
| TTI | < 3.5s | Lighthouse |
| FCP | < 1.8s | Lighthouse |

Biện pháp: route-based code splitting (mỗi module CRM/WMS/CEO lazy import); Recharts + zxing chỉ load ở route cần; tree-shake lucide-react (import từng icon); `react-markdown` lazy trong ChatPanel. **Lighthouse CI** trong GitHub Actions, fail build nếu vượt budget > 10%.

---

## 11. i18n strategy — i18n-ready, chưa dịch EN

**Quyết định: tách chuỗi ra ngay từ đầu (i18n-ready), nhưng chỉ có 1 locale `vi`. Chưa dịch EN.** Lý do: thị trường nội địa VN, dịch EN bây giờ là chi phí chết; nhưng hardcode chuỗi thì sau thêm EN phải sửa khắp nơi. Tách chuỗi ngay = chi phí ~0, giữ cửa mở.

### 11.1 Frontend — react-i18next
```ts
// src/lib/i18n.ts
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import vi from '../locales/vi.json';
i18n.use(initReactI18next).init({
  resources: { vi: { translation: vi } },
  lng: 'vi', fallbackLng: 'vi', interpolation: { escapeValue: false },
});
```
```tsx
const { t } = useTranslation();
<button>{t('quote.create')}</button>     // thay vì "Tạo báo giá" hardcode
```
Chuỗi gom vào `src/locales/vi.json`. Khi cần EN: thêm `en.json` + switcher, không sửa component. ESLint rule `i18next/no-literal-string` (chỉ bật ở thư mục pages/components để chặn hardcode mới).

### 11.2 Backend — Django gettext
Message lỗi/email/PDF dùng `gettext`:
```python
from django.utils.translation import gettext_lazy as _
{"detail": _("Tài khoản hoặc mật khẩu không đúng"), "code": "AUTH_INVALID"}
```
`makemessages -l vi` → `locale/vi/LC_MESSAGES/django.po`. Hiện chỉ compile `vi`. Enum `verbose_name` đã tách sẵn (B.2 dùng tiếng Việt) — đổi sang `_()` để i18n-ready.

### 11.3 Sidecar (chat)
Bot trả lời tiếng Việt là **nội dung sinh ra**, không phải UI string — không qua i18n. Nếu sau cần EN cho chat: thêm system prompt theo `Accept-Language` / param `lang`. Hiện để VI.

### 11.4 Dữ liệu song ngữ sẵn có
Catalog đã có `display_name_vi` + `display_name_en` (B.2 §3.1) và `category_vocabulary` map VI↔EN — nếu sau làm EN, phần dữ liệu sản phẩm gần như đã sẵn, chỉ thiếu UI string.

---

## Tổng kết — artifact kèm theo file này

| File | Vị trí | Trạng thái |
| --- | --- | --- |
| `requirements.txt` + `requirements-dev.txt` | backend/ | ✅ chạy được |
| `chatbot/requirements.txt` | chatbot/ | ✅ |
| `package.json` | frontend/ | ✅ |
| `docker-compose.yml` | root | ✅ |
| `seed_from_json.py` | apps/catalog/management/commands/ | ✅ skeleton đầy đủ |
| `ci.yml` | .github/workflows/ | ✅ |
| `backup.sh` | scripts/ | ✅ |

Sau khi có các file này, dev có thể `docker-compose up` + `manage.py migrate` + `seed_from_json` để dựng môi trường dev đầy đủ.
