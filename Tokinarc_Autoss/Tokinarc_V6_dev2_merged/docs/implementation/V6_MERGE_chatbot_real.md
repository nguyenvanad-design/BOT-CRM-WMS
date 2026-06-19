# MERGE NOTE — Gộp chatbot THẬT (v8.0) vào dev2 (CRM/WMS/CEO)

> Ngày gộp: 2026-06. Mục tiêu: đưa chatbot đã build & test ổn vào chung repo với
> backend Django (CRM/WMS/Sales/Analytics) **mà không xung đột**, KHÔNG sửa code chatbot.

---

## 1. Kết luận: hai service ĐỘC LẬP, không xung đột logic

| | Chatbot (v8.0) | Backend dev2 (CRM/WMS/CEO) |
|---|---|---|
| Framework | FastAPI | Django REST |
| Auth | **X-API-Key** (`TOKINARC_API_KEY`) | **JWT/JWKS** |
| Dữ liệu | TỰ chứa: `data/tokinarc_data_v19.json` + FAISS `indexes/` | Postgres |
| Port | 8080 | 8000 |
| Phụ thuộc nhau? | **KHÔNG** — chatbot không gọi Django | — |

Chatbot tool = tra cứu catalog/phụ tùng (`lookup_part`, `search_parts`,
`find_upsell`, `check_compatibility`, `compare_parts`, `get_torches`...), chạy trên
dữ liệu nội bộ + retrieval (bge-m3 + BM25 + PQA). Nó **không** đụng CRM/WMS/đơn hàng,
nên không tranh chấp gì với backend.

→ Gặp nhau DUY NHẤT ở nginx: `/api/chat` → chatbot:8080, `/api/` → django:8000.

---

## 2. Những gì đã chỉnh khi gộp (KHÔNG đụng code chatbot)

1. **`chatbot/`**: thay bản sidecar rút gọn cũ (JWT + 27 tool gọi Django) bằng
   **toàn bộ chatbot thật** từ bot.rar (core/, data/, indexes/, vision, eval, logs,
   legacy, archive_old — giữ NGUYÊN tất cả).
2. **`chatbot/Dockerfile`** (mới): python:3.11-slim + torch/sentence-transformers/faiss,
   bundle data+indexes, `uvicorn main:app --port 8080`. (Bản thật không kèm Dockerfile.)
3. **`infra/docker-compose.yml`** — service `chatbot`:
   - Bỏ `depends_on: [postgres, django]` (chatbot không cần chúng).
   - Healthcheck đổi `/api/v1/health/ready` → `/` (route chat UI, không cần key).
     `/api/v1/health` của bản thật yêu cầu X-API-Key nên không gọi trần được.
   - Thêm volume `hf_cache` cache model bge-m3, `start_period: 120s` cho lần load đầu.
4. **`README.md`**: cập nhật mô tả cây `chatbot/` cho khớp v8.0.

Backend / frontend / docs khác: GIỮ NGUYÊN (gồm các fix trước:
FE Dockerfile build thật, sales event handlers + apps.ready, dev README).

---

## 3. Việc CÒN LẠI cho bạn (cấu hình runtime, không phải lỗi gộp)

### 3.1 Hai file `.env`
- `chatbot/.env` — có `GEMINI_API_KEY`, `TOKINARC_API_KEY` (chatbot tự đọc qua
  `load_dotenv`). **Đang chứa key thật** → đừng push lên git public
  (`.gitignore` đã loại `.env`, nhưng cẩn thận khi share file zip).
- `.env` ở repo root — biến cho dev2 (PG/JWT/MinIO). Compose `chatbot` có
  `env_file: [../.env]` nhưng chatbot chỉ thực sự cần key trong `chatbot/.env`.
  Có thể gộp biến chatbot vào `.env` root nếu muốn 1 nguồn duy nhất.

### 3.2 Auth header ở nginx (cần kiểm tra khi chạy thật)
`nginx/public.conf` + `internal.conf` forward header `Authorization` xuống chatbot,
nhưng chatbot thật xác thực bằng **`X-API-Key`**. Caller (FE/Zalo) phải gửi
`X-API-Key: <TOKINARC_API_KEY>` khi gọi `/api/chat/`. Nếu muốn nginx tự gắn key,
thêm `proxy_set_header X-API-Key <key>;` trong block `location /api/chat/`.
(Để bạn quyết — không sửa sẵn vì đụng tới chính sách bảo mật.)

### 3.3 Model bge-m3 (~2GB)
Tải runtime từ HuggingFace lần đầu → cache vào volume `hf_cache`. Lần build/đầu
chạy sẽ lâu; các lần sau dùng cache. Nếu deploy offline, pre-download model vào
volume trước.

### 3.4 GPU (tùy chọn)
`requirements.txt` ghi torch CPU mặc định. Production của bạn dùng torch 2.6.0+cu124.
Nếu cần GPU trong Docker: đổi base image sang CUDA + cài torch cu124 + bật
`deploy.resources.reservations.devices` trong compose.

---

## 4. Lệnh chạy

```bash
cd <repo>
# (dev2) tạo khóa + env cho backend
bash infra/scripts/gen_keys.sh
cp infra/.env.example .env && nano .env

# chatbot đã có chatbot/.env sẵn (key thật) — không cần làm gì thêm

docker compose -f infra/docker-compose.yml --env-file .env up -d --build
# Lần đầu: chatbot tải bge-m3 (~2GB) → chờ start_period 120s+.
```

Kiểm tra:
- `curl http://localhost:8080/` → trả vision_chat.html (chatbot sống)
- `curl -H "X-API-Key: <key>" http://localhost:8080/api/v1/health` → trạng thái module
- Django: `curl http://localhost:8000/api/health/ready/`
