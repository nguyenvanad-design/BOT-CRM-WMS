# DEV SETUP — Onboarding cho dev mới

> **Thời gian**: ~30 phút từ `git clone` đến chạy được full stack local.
> **Yêu cầu máy**: Python 3.12, Node 20, (tùy chọn) Docker.

---

## 1. Cài đặt môi trường (5 phút)

### Python 3.12

```bash
# macOS
brew install python@3.12
# Ubuntu
sudo apt install python3.12 python3.12-venv python3.12-dev
# Windows: tải installer từ python.org
```

### Node 20

```bash
# Khuyến cáo dùng nvm
nvm install 20 && nvm use 20
```

### Postgres + pgvector (tùy chọn — chỉ cần cho production-grade test)

Local dev dùng SQLite OK 95% trường hợp. Chỉ cần Postgres khi:
- Test `pgvector` semantic search
- Test LISTEN/NOTIFY event bus
- Test materialized views

```bash
# Docker option (đơn giản nhất)
docker run --name pg-tokinarc -e POSTGRES_PASSWORD=tokinarc -p 5432:5432 -d pgvector/pgvector:pg16
```

---

## 2. Clone + setup backend (10 phút)

```bash
git clone <repo-url> tokinarc
cd tokinarc/backend

# Tạo venv
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Cài dependencies
pip install -r requirements-dev.txt
```

> **Lưu ý**: `requirements-dev.txt` đã include cả `requirements.txt` + tools test (pytest, factory-boy). KHÔNG cần cài thêm.

### Chạy migrations + test ngay để verify

```bash
export DJANGO_SETTINGS_MODULE=tokinarc.settings.test
python manage.py migrate
pytest apps/ -q
# Mong đợi: 71 passed in ~10s
```

Nếu fail ngay đây → xem [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) §1.

### Seed data thật (837 part, 121 torch)

```bash
# Tạo admin + 7 user mỗi role (default password = changeme)
python manage.py seed_users_roles --admin-password=admin123

# Seed catalog từ JSON v19
python manage.py seed_from_json data/tokinarc_data_v19.json

# Seed warehouse + bin mẫu
python manage.py seed_warehouse
```

### Chạy dev server

```bash
python manage.py runserver
# → http://127.0.0.1:8000/api/health/live/ trả {"status":"ok"}
```

---

## 3. Setup chatbot (5 phút)

> Chatbot THẬT v8.0: FastAPI độc lập, auth `X-API-Key`, tự chứa data + FAISS
> index, KHÔNG gọi Django. Chi tiết đầy đủ: [`../../chatbot/README.md`](../../chatbot/README.md).

Mở terminal mới:

```bash
cd chatbot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt    # torch + sentence-transformers + faiss → hơi lâu

# .env đã có sẵn key (GEMINI_API_KEY, TOKINARC_API_KEY). Nếu chưa, xem chatbot/README.md §4.

uvicorn main:app --reload --port 8080
```

Lần đầu tải model bge-m3 (~2GB) → cache `~/.cache/huggingface`. Thấy log
`✅  All modules ready` là xong.

### Smoke test chatbot

```bash
# Lấy key từ .env
export TOKINARC_API_KEY=$(grep TOKINARC_API_KEY chatbot/.env | cut -d= -f2)

# 1. Sống? (route '/' không cần key)
curl -s http://localhost:8080/ | head -c 60

# 2. Health (cần key)
curl -s http://localhost:8080/api/v1/health -H "X-API-Key: $TOKINARC_API_KEY"

# 3. Hỏi thật
curl -s -X POST http://localhost:8080/api/v2/query \
  -H "X-API-Key: $TOKINARC_API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "béc hàn cho mỏ 350A", "session_id": "dev1"}'
```

> Chatbot và backend Django KHÔNG gọi nhau. Có thể chạy độc lập từng cái.

---

## 4. Setup frontend (5 phút)

Mở terminal mới:

```bash
cd frontend
npm install         # ~30s lần đầu

# Dev server (proxy /api → localhost:8000)
npm run dev
# → http://localhost:5173

# Build production (verify TypeScript)
npm run build
# → typecheck 0 lỗi, dist/ ~10KB CSS + 322KB JS
```

### Đăng nhập thử

Mở `http://localhost:5173`:
- Username: `admin`
- Password: `admin123` (từ `seed_users_roles --admin-password=`)

→ Vào trang Customers, nếu chưa seed customer thì sẽ rỗng. Test tạo customer qua admin panel hoặc:

```bash
cd backend
python manage.py shell -c "
from apps.crm.models import Customer
from apps.accounts.models import User
admin = User.objects.get(username='admin')
Customer.objects.create(code='KH-0001', name='Cong ty hop kim Viet', segment='steel', region='HCM', status='active', owner=admin)
Customer.objects.create(code='KH-0002', name='Co khi Bach Khoa', segment='fabrication', region='Hanoi', status='potential', owner=admin)
"
```

Refresh trang FE — 2 KH hiện ra.

---

## 5. Verify full stack (5 phút)

```
Terminal 1: backend runserver  (port 8000)
Terminal 2: chatbot uvicorn    (port 8080)
Terminal 3: frontend npm dev   (port 5173)
```

Mở 3 tab browser:

| URL | Mong đợi |
|---|---|
| `http://localhost:8000/admin/` | Login admin Django, xem CRM/WMS/Sales table |
| `http://localhost:5173/` | Login → Customers page với KH vừa seed |
| `http://localhost:8000/api/v1/catalog/parts/search/?q=bep` | JSON list 10 part match "bep" |
| `http://localhost:8080/` | Chat UI chatbot (vision_chat.html) |

Nếu cả 4 OK → môi trường sẵn sàng.

---

## 6. Workflow code hàng ngày

### Trước khi bắt đầu feature

```bash
git pull
cd backend
python manage.py migrate              # apply migration mới từ team
python manage.py makemigrations --check --dry-run  # đảm bảo không có drift
pytest apps/ -q                       # baseline test pass
```

### Trong khi code

```bash
# Watch test thay đổi (ptw cài thêm: pip install pytest-watch)
ptw apps/<app>/

# Lint trước khi commit
ruff check backend/

# FE: typecheck thường xuyên
cd frontend && npm run typecheck
```

### Trước khi `git push`

Bắt buộc 5 lệnh — xem [`EXTENDING.md`](../../EXTENDING.md) §8:

```bash
cd backend
# 1. Drift check
python manage.py makemigrations --check --dry-run

# 2. Test
pytest apps/ -q

# 3. Lint
ruff check .

# 4. (FE) typecheck + build
cd ../frontend && npm run build
```

> Lưu ý: bước "dump_roles --check" cũ đã BỎ — chatbot thật không còn
> `roles_generated.py`. Roles vẫn single-source ở `accounts/roles.py` cho Django.

---

## 7. IDE setup (VS Code)

`.vscode/settings.json` khuyến cáo:

```json
{
  "python.defaultInterpreterPath": "backend/.venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["apps", "-q"],
  "python.envFile": "${workspaceFolder}/backend/.env.local",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  },
  "[typescriptreact]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "typescript.tsdk": "frontend/node_modules/typescript/lib",
  "tailwindCSS.experimental.classRegex": [
    ["clsx\\(([^)]*)\\)", "(?:'|\"|`)([^']*)(?:'|\"|`)"]
  ]
}
```

Extensions khuyến cáo:
- Python (Microsoft)
- Ruff (Charlie Marsh)
- Tailwind CSS IntelliSense
- Prettier
- GitLens

---

## 8. Env var cheatsheet

`backend/.env.local` (KHÔNG commit):

```bash
DJANGO_SETTINGS_MODULE=tokinarc.settings.test  # dùng SQLite local
DJANGO_SECRET_KEY=dev-only-not-for-prod
ALLOW_HS256_DEV=1   # JWT HS256 dev fallback
```

`chatbot/.env` (đã có sẵn — KHÔNG commit nếu chứa key thật):

```bash
GEMINI_API_KEY=                  # rỗng = pipeline LLM không chạy
GEMINI_MODEL=gemini-2.0-flash
TOKINARC_API_KEY=dev-tokinarc-2026   # client gửi qua header X-API-Key
TOKINARC_ENV=dev
```

`frontend/.env.local`:

```bash
VITE_API_BASE=/api/v1                   # default
```

---

## 9. Đọc tiếp

Bây giờ môi trường đã sẵn sàng, tùy mục đích:

- **Code backend / thêm endpoint** → [`API_REFERENCE.md`](API_REFERENCE.md)
- **Code/sửa chatbot** → [`../../chatbot/README.md`](../../chatbot/README.md) (chatbot thật v8.0)
- **Thêm page FE** → [`FRONTEND_GUIDE.md`](FRONTEND_GUIDE.md)
- **Thêm event async** → [`EVENTS_HANDLERS.md`](EVENTS_HANDLERS.md)
- **Lỗi khi chạy** → [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)
- **Quy ước commit + checklist** → [`../../EXTENDING.md`](../../EXTENDING.md)
