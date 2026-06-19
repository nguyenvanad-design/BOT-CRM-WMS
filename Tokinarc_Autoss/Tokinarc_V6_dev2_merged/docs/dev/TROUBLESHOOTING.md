# TROUBLESHOOTING — Lỗi thường gặp + fix

> Tra cứu khi gặp lỗi. Sắp xếp theo "triệu chứng" → "nguyên nhân" → "fix".
> Nếu lỗi không có ở đây + đã debug 30 phút → ping team trước khi đào sâu thêm.

---

## 1. Backend test fail ngay lần đầu

### Triệu chứng

```
pytest apps/ -q
# ERROR ...: django.db.utils.OperationalError: near "EXTENSION"
# hoặc
# ImportError: cannot import name 'X' from 'apps.Y'
```

### Nguyên nhân + Fix

**A. Quên `migrate` trước test trên DB persistent**

```bash
python manage.py migrate
pytest apps/ --create-db -q   # --create-db: tạo lại test DB
```

**B. PartEmbedding migration không guard vendor đúng**

Xem [`EXTENDING.md`](../../EXTENDING.md) §9.1. Nếu vừa sửa `catalog/models.py` PartEmbedding mà không viết migration tay → migrate vỡ SQLite.

```bash
# Verify
python manage.py makemigrations --check --dry-run
# Nếu drift → đọc EXTENDING §9.1
```

**C. Test ImportError vì circular**

Khi import trong handler/service: dùng lazy import trong function body, đừng top-level.

---

## 2. `makemigrations --check` báo drift mà code không đổi

### Triệu chứng

```
Migrations for 'catalog':
  catalog/migrations/0002_alter_torch.py
    - Alter index catalog_torch_xxx → catalog_torch_yyy
```

Mà bạn chưa sửa model.

### Nguyên nhân

Index không đặt tên tường minh → Django tự sinh tên hash khác môi trường khác.

### Fix

Thêm `name=` cho mọi index trong `class Meta`:

```python
class Meta:
    indexes = [
        # SAI:
        models.Index(fields=['status', 'created_at']),

        # ĐÚNG:
        models.Index(fields=['status', 'created_at'], name='thing_status_created_idx'),
    ]
```

Pattern naming: `<app_table>_<fields_short>_idx`. Tối đa 30 ký tự (Postgres limit).

---

## 3. (BỎ) CI "Check role tables sync"

> ⚠️ Bước CI này đã được GỠ sau khi gộp chatbot thật. Chatbot v8.0 không còn
> `roles_generated.py`. Nếu CI cũ của bạn vẫn còn bước này, xóa nó khỏi
> `.github/workflows/ci.yml`.
>
> Roles vẫn là single-source ở `backend/apps/accounts/roles.py` cho phía Django.
> Khi FE cần `roles.ts`:
> ```bash
> python manage.py dump_roles --format=ts --out ../frontend/src/lib/auth/roles.ts
> ```

---

## 4. Chatbot trả 401 / 403

### Triệu chứng

```bash
curl -X POST localhost:8080/api/v2/query -d '{"query":"..."}'
# 401 {"detail":"Invalid or missing API key"}
```

### Nguyên nhân + Fix

Chatbot thật v8.0 auth bằng **`X-API-Key`** (không phải JWT). Phải gửi header:

```bash
curl -X POST localhost:8080/api/v2/query \
  -H "X-API-Key: $TOKINARC_API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"béc hàn 350A","session_id":"t1"}'
```

- Key lấy từ `chatbot/.env` (`TOKINARC_API_KEY`).
- Qua nginx: `public.conf`/`internal.conf` forward header `Authorization`, KHÔNG
  forward `X-API-Key`. Nếu gọi chatbot qua nginx mà bị 401 → thêm
  `proxy_set_header X-API-Key <key>;` vào block `location /api/chat/`, hoặc cho
  client gửi thẳng `X-API-Key`. (Xem `V6_MERGE_chatbot_real.md` §3.2.)
- `TOKINARC_ENV=production` mà chưa đổi key khỏi default → server raise lúc start.

---

## 5. Chatbot: lỗi khi gọi tool / tool trả _fail

### Triệu chứng

```
UNKNOWN_TOOL:get_xyz   (tool không có trong TOOL_HANDLERS)
TOOL_ERROR:KeyError:... (tool chạy lỗi)
```

### Nguyên nhân + Fix

Chatbot thật dùng tool **in-process** ở `core/tool_wrappers.py` (KHÔNG phải client
gọi Django như tài liệu cũ). 11 tool đăng ký trong `TOOL_HANDLERS`.

- Thêm tool: viết function + đăng ký `TOOL_HANDLERS` + thêm schema vào
  `core/system_prompts.py::TOOL_SCHEMA`. Xem `chatbot/README.md` §7.
- Test tool độc lập (không qua LLM):
  ```python
  from core.tool_wrappers import dispatch
  print(dispatch("search_parts", {"query": "béc hàn", "top_k": 3}))
  ```
- Nếu tool đọc data sai/thiếu → có thể index lệch data, chạy `python rebuild_index.py`.

---

## 6. Chatbot trả stub khi đã set GEMINI_API_KEY

### Triệu chứng

```bash
curl -X POST localhost:8080/api/v2/query ...
# {"text": "Tính năng LLM chưa cấu hình...", "confidence": {"tier": "stub", "reason": "llm_disabled"}}
```

Đã `export GEMINI_API_KEY="..."`.

### Nguyên nhân

`main.py`/orchestrator đọc `GEMINI_API_KEY` tại import/startup. Process chatbot đang chạy không thấy env mới; hoặc key để rỗng trong `chatbot/.env`.

### Fix

```bash
# Set key trong chatbot/.env rồi restart
pkill -f "uvicorn main:app"
uvicorn main:app --reload --port 8080
```

> Production Docker: set trong `chatbot/.env` hoặc `environment:` của compose, không `export` runtime. Key rỗng → server vẫn lên nhưng pipeline LLM trả stub.

---

## 7. Migrate fail trên Postgres production

### Triệu chứng

```
django.db.utils.ProgrammingError: relation "wms_inventory" does not exist
```

### Nguyên nhân

Migration depend tham chiếu app/migration không tồn tại theo tên cụ thể.

### Fix

```bash
python manage.py showmigrations | grep '\[X\]' | wc -l
# So với git log migration files
```

Nếu mismatch:
1. Backup DB ngay (`pg_dump`)
2. Check `django_migrations` table: `SELECT app, name FROM django_migrations ORDER BY id`
3. Đối chiếu với `apps/<app>/migrations/` files
4. Đừng xóa rows `django_migrations` trừ khi 100% chắc

> **Đừng** sửa `0001_initial` đã commit (xem `EXTENDING.md` §9.3). Thêm migration mới.

---

## 8. WAL archive lỗi `mc: not found`

### Triệu chứng

Postgres log:
```
ERROR: archive command failed with exit code 127
mc: not found
```

### Nguyên nhân

Stock `postgres:16` image không có `mc` (MinIO client). `backup.sh` dùng `mc` đẩy WAL → MinIO.

### Fix

Đảm bảo dùng custom image `infra/postgres/Dockerfile`:

```dockerfile
FROM postgres:16
RUN apt-get update && apt-get install -y wget && \
    wget https://dl.min.io/client/mc/release/linux-amd64/mc && \
    chmod +x mc && mv mc /usr/local/bin/
```

Compose:
```yaml
postgres:
  build: ./infra/postgres   # KHÔNG dùng image: postgres:16
```

---

## 9. FE "401 Unauthorized" loop liên tục

### Triệu chứng

Browser network tab: `/auth/refresh/` gọi liên tục, mỗi lần fail → tiếp tục → loop.

### Nguyên nhân

Refresh token đã hết hạn / blacklist nhưng FE không clear.

### Fix

Mở DevTools console:
```javascript
localStorage.removeItem('tokinarc_access')
localStorage.removeItem('tokinarc_refresh')
localStorage.removeItem('tokinarc_user')
location.assign('/login')
```

Sau đó login lại.

> **Code fix gốc**: `api.ts` đã có guard `_retry: true` (chỉ refresh 1 lần). Nếu vẫn loop → kiểm tra:
> - Có gọi `/auth/refresh/` ở chỗ khác không qua `api` instance?
> - `_retry` flag bị overwrite bởi axios config global?

---

## 10. FE build OK nhưng production CORS lỗi

### Triệu chứng

Production browser:
```
Access to XMLHttpRequest at 'https://internal.tokinarc.vn/api/v1/...' from origin 'https://internal.tokinarc.vn'
has been blocked by CORS policy
```

Cùng origin sao CORS?

### Nguyên nhân

FE đang build với `VITE_API_BASE=http://localhost:8000` (absolute URL) → request thẳng `localhost` từ browser production → CORS.

### Fix

Build production phải dùng relative path:

```bash
# .env.production
VITE_API_BASE=/api/v1
```

Nginx proxy `/api/v1` → Django. Browser thấy cùng origin.

---

## 11. Worker container crash loop

### Triệu chứng

```bash
docker compose logs worker --tail 20
# python manage.py run_eventbus_listener
# Unknown command: 'run_eventbus_listener'
```

### Nguyên nhân

Command không tồn tại trong app nào. Trước fix2, `worker_entrypoint.sh` gọi command nhưng file chưa tạo.

### Fix

Verify file tồn tại:

```bash
ls backend/apps/common/management/commands/run_eventbus_listener.py
# Phải có
```

Nếu thiếu → V6.C-fix2 bị mất. Xem `docs/implementation/V6_C_5_Fix2_Changelog.md` để khôi phục.

---

## 12. Seed `tokinarc_data_v19.json` fail

### Triệu chứng

```
python manage.py seed_from_json data/tokinarc_data_v19.json
# IntegrityError: NOT NULL constraint failed: catalog_part.display_name_vi
```

### Nguyên nhân + Fix

**A. File JSON v19 không có ở `data/`**

```bash
ls backend/data/tokinarc_data_v19.json
# Phải tồn tại. Copy từ project knowledge nếu thiếu.
```

**B. Part thiếu `display_name_vi`**

JSON v19 nên đầy đủ. Nếu vẫn lỗi → kiểm tra phiên bản JSON (header có ghi `version: v19`).

---

## 13. Test `IntegrityError: UNIQUE constraint failed: crm_customer.code`

### Triệu chứng

```
django.db.utils.IntegrityError: UNIQUE constraint failed: crm_customer.code
```

### Nguyên nhân

Test fixture tạo customer với code cứng `'KH-0001'` mà test khác đã tạo trong cùng DB.

### Fix

Dùng `factory.Sequence` thay vì hardcode:

```python
# SAI
def test_x():
    Customer.objects.create(code='KH-0001', ...)

# ĐÚNG
class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer
    code = factory.Sequence(lambda n: f'KH-{n:04d}')
    name = factory.Sequence(lambda n: f'Cong ty {n}')
```

---

## 14. `npm install` quá chậm / fail

### Triệu chứng

```
npm error code ETIMEDOUT
npm error errno -110
```

Hoặc tải > 5 phút.

### Nguyên nhân + Fix

**A. Mạng yếu / proxy**

```bash
npm config set registry https://registry.npmjs.org/
npm config set fetch-timeout 60000
```

**B. lock file conflict**

```bash
rm -rf node_modules package-lock.json
npm install
```

**C. node version sai**

```bash
node --version    # Phải 20.x
nvm use 20
```

---

## 15. `pytest` chạy chậm > 30s

### Triệu chứng

Test pass nhưng mất 60-90s mỗi lần.

### Nguyên nhân

`--create-db` flag tạo lại DB từ migration mỗi lần.

### Fix

Dùng `pytest-django` reuse DB:

```bash
pytest apps/ --reuse-db -q     # nhanh hơn 5-10x
# Lần đầu vẫn migrate, lần sau reuse
```

Khi migration thay đổi:
```bash
pytest apps/ --create-db -q    # tạo lại
```

`pytest.ini` đã set sẵn `--reuse-db` default — chỉ override khi cần.

---

## 16. Logs JSON không parse được

### Triệu chứng

```
{"asctime": "...", "name": "tokinarc.chatbot", "msg": "query_received", "extra": "...
ValueError: Unterminated string
```

### Nguyên nhân

`python-json-logger` không escape đúng khi extra chứa newline / quote.

### Fix

Trong code log, đừng pass object phức tạp:

```python
# SAI
logger.info("event", extra={"user": user_obj, "query": "multi\nline\nstring"})

# ĐÚNG
logger.info("event", extra={"user_id": str(user_obj.id), "query_len": len(query)})
```

---

## 17. Postgres connection pool exhausted

### Triệu chứng

```
django.db.utils.OperationalError: FATAL: sorry, too many clients already
```

### Nguyên nhân

Django default mở 1 conn / process. Worker + gunicorn 4 worker × 4 thread × 2 conn = 32 conn. Postgres default 100 conn → OK. Nếu vỡ:

### Fix

**A. Tăng Postgres `max_connections`**

```
# postgresql.conf
max_connections = 200
```

**B. Dùng PgBouncer / Django CONN_MAX_AGE**

```python
# settings/production.py
DATABASES['default']['CONN_MAX_AGE'] = 600
```

---

## 18. Bot trả "Tôi đã tìm kiếm khá lâu nhưng chưa có kết quả..."

### Triệu chứng

```json
{"confidence": {"warnings": ["MAX_HOPS"]}, "tools_used": [...4 tool...]}
```

### Nguyên nhân

Gemini gọi > 4 tool hop nhưng vẫn chưa có câu trả lời. Set `GEMINI_MAX_TOOL_HOPS=4` mặc định.

### Fix

```bash
# .env hoặc env runtime
export GEMINI_MAX_TOOL_HOPS=6
```

Hoặc cải thiện schema description để Gemini gọi tool đúng từ lần đầu.

> Monitor: nếu MAX_HOPS log nhiều lần trong production, kiểm tra log `tools_used` để biết Gemini đang lặp tool nào → có thể thêm `description` rõ hơn hoặc tách tool.

---

## 19. `from apps.X import Y` ImportError

### Triệu chứng

```
ImportError: cannot import name 'Lead' from 'apps.crm.models'
```

Mà file đã có class `Lead`.

### Nguyên nhân + Fix

**A. Circular import**

Lazy import trong function:

```python
def some_function():
    from apps.crm.models import Lead   # lazy
    return Lead.objects.all()
```

**B. App chưa wire vào `INSTALLED_APPS`**

```python
# settings/base.py
INSTALLED_APPS = [
    'django.contrib.admin', ...,
    'apps.crm',   # ← phải có
]
```

**C. Quên `apps.py` trong app folder**

```python
# apps/<app>/apps.py phải tồn tại
from django.apps import AppConfig
class XConfig(AppConfig):
    name = 'apps.<app>'
```

---

## 20. Docker compose build chậm > 5 phút

### Triệu chứng

`docker compose build` mất 5-10 phút mỗi lần.

### Fix

**A. Layer caching**

Đảm bảo `COPY requirements*.txt ./` trước `COPY . .`:

```dockerfile
# ĐÚNG — install ở layer trước, chỉ rebuild khi requirements đổi
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .
```

**B. BuildKit cache mount**

```dockerfile
# syntax=docker/dockerfile:1.4
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

**C. `.dockerignore`**

```
node_modules
.venv
__pycache__
*.pyc
.git
```

---

## Nếu không tìm thấy lỗi ở đây

1. Tìm trong `git log --all --oneline | grep <keyword>` — có thể đã sửa rồi
2. Tìm trong `docs/implementation/V6_C_*_Changelog.md`
3. Ping team Slack channel `#tokinarc-dev`
4. Cuối cùng, mở issue với template:
   - Triệu chứng (full log + command)
   - Step reproduce
   - Đã thử gì
   - Environment (OS, Python, Node, Postgres version)
