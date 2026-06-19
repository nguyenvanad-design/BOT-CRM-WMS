# Tokinarc Chatbot (v8.0) — FastAPI + Gemini + Retrieval

> Service chatbot **độc lập**, tự chứa dữ liệu sản phẩm + FAISS index.
> KHÔNG gọi Django backend. Auth bằng `X-API-Key`. Chạy port 8080.
>
> Đây là chatbot THẬT đã build & test ổn (khác bản sidecar JWT/27-tool mô tả
> trong các tài liệu kiến trúc B1/B5 cũ — xem cảnh báo ở đầu những file đó).

---

## 1. Kiến trúc 1 phút

```
POST /api/v2/query  (+ X-API-Key)
  → verify_api_key
  → vision (nếu có ảnh: analyze → build_query)
  → Gemini orchestrator (function-calling loop, tối đa 4 hop)
       └─ gọi tool (core/tool_wrappers.py) trên retrieval engine:
            FAISS vector + BM25 + Procedural-QA + data_store
  → QueryResponse {text, confidence, ...}
```

Toàn bộ chạy trong **1 process FastAPI** (`main.py`). Engine nằm ở `core/`,
dữ liệu ở `data/`, index ở `indexes/`.

---

## 2. Yêu cầu

- Python 3.11
- ~3GB đĩa trống (model BAAI/bge-m3 tải runtime ~2GB + index)
- (Tùy chọn) GPU CUDA 12.4 cho torch — mặc định chạy CPU vẫn được
- GEMINI_API_KEY (https://aistudio.google.com/apikey) — để rỗng thì pipeline
  LLM không chạy, nhưng server vẫn lên (các module retrieval vẫn ready)

---

## 3. Setup local (dev)

```bash
cd chatbot
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # torch + sentence-transformers + faiss → hơi lâu

# .env đã có sẵn (GEMINI_API_KEY, TOKINARC_API_KEY...). Nếu chưa, tạo theo §4.

uvicorn main:app --reload --port 8080
```

Lần chạy đầu sẽ tải model bge-m3 (~2GB) từ HuggingFace → cache vào
`~/.cache/huggingface`. Các lần sau dùng cache, khởi động nhanh.

Khi thấy log `✅  All modules ready in ...ms` là sẵn sàng.

### Smoke test nhanh

```bash
# 1. Chatbot sống? (route '/' KHÔNG cần key — trả vision_chat.html)
curl -s http://localhost:8080/ | head -c 80

# 2. Health (CẦN key)
curl -s http://localhost:8080/api/v1/health -H "X-API-Key: $TOKINARC_API_KEY" | python -m json.tool

# 3. Hỏi thật
curl -s -X POST http://localhost:8080/api/v2/query \
  -H "X-API-Key: $TOKINARC_API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "béc hàn cho mỏ 350A", "session_id": "test1"}'
```

---

## 4. Biến môi trường (.env)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `GEMINI_API_KEY` | (rỗng) | Key Gemini. Rỗng → pipeline LLM không chạy |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Model Gemini dùng |
| `TOKINARC_API_KEY` | `dev-tokinarc-2026` | Key client phải gửi qua header `X-API-Key` |
| `TOKINARC_ENV` | `dev` | `production` → bắt buộc set API key thật (fail nếu còn default) |
| `RATE_LIMIT_RPM` | `60` | Giới hạn request/phút mỗi IP |
| `TOKINARC_CORS_ORIGINS` | `*` | CORS origins (phẩy ngăn cách) |
| `TOKINARC_LOG_DIR` | `logs` | Thư mục ghi `queries.jsonl` |
| `TOKINARC_DATA` | (auto) | Override path data; mặc định auto-detect `data/tokinarc_data_v*.json` bản cao nhất |
| `TOKINARC_MAX_TOOL_CALLS` | `4` | Số hop function-calling tối đa |
| `REDIS_URL` | (rỗng) | Session store; rỗng → fallback in-memory |

> ⚠️ Production: phải set `TOKINARC_ENV=production` + `TOKINARC_API_KEY` thật +
> `GEMINI_API_KEY` thật, nếu không server raise lúc khởi động.

---

## 5. Endpoint

| Method | Path | Auth | Vai trò |
|---|---|---|---|
| GET | `/` | không | Chat UI (`vision_chat.html`) — cũng dùng làm liveness |
| POST | `/api/v2/query` | X-API-Key | Pipeline chính (Gemini function-calling) |
| POST | `/api/v2/stream` | X-API-Key | Streaming SSE |
| POST | `/api/v5/query` | X-API-Key | Tương thích cũ → forward v2 |
| POST | `/api/v5/stream` | X-API-Key | Streaming bản v5 |
| DELETE | `/api/v5/session/{id}` | X-API-Key | Xóa session |
| GET | `/api/v5/sessions/stats` | X-API-Key | Thống kê session |
| POST | `/api/v1/search` | X-API-Key | Vector search trực tiếp |
| GET | `/api/v1/health` | X-API-Key | Trạng thái các module |
| WS | `/ws/query` | (trong payload) | WebSocket → V2 |

---

## 6. Dữ liệu & index

| Thư mục/File | Nội dung |
|---|---|
| `data/tokinarc_data_v19.json` | Catalog parts + torch (nguồn chính) |
| `data/procedural_qa_kb.jsonl` | Knowledge base hỏi-đáp quy trình |
| `data/assembly_procedures_v1_3.json` | Quy trình lắp ráp |
| `data/Tokinarc_PriceList_Mock_v1.xlsx` | Bảng giá mock |
| `indexes/tokinarc_faiss.index` + `.pkl` | FAISS vector index của catalog |
| `indexes/procedural_qa_idx/` | FAISS index cho Procedural-QA |

### Rebuild index sau khi đổi data

```bash
python rebuild_index.py            # rebuild cả vector + PQA
python rebuild_index.py --vec      # chỉ vector
python rebuild_index.py --pqa      # chỉ PQA
python rebuild_index.py --force    # ép rebuild dù index đã có
```

Chạy lại mỗi khi sửa `data/tokinarc_data_v*.json` hoặc `procedural_qa_kb.jsonl`,
nếu không kết quả search sẽ lệch với data mới.

---

## 7. Thêm 1 tool mới cho chatbot

Chatbot thật KHÔNG dùng mô hình "5 file gọi Django REST" (đó là chatbot sidecar
cũ — bỏ qua `CHATBOT_TOOL_GUIDE.md`). Tool ở đây là **function in-process** chạy
trên retrieval engine. Thêm tool qua 2 chỗ:

1. **`core/tool_wrappers.py`** — viết function `def my_tool(...) -> dict:` trả về
   dict serializable (dùng `_ok(...)` / `_fail(...)`), rồi đăng ký vào
   `TOOL_HANDLERS = { ..., "my_tool": my_tool }`.
2. **`core/system_prompts.py`** — thêm schema vào `TOOL_SCHEMA` (name, description,
   parameters) để Gemini biết gọi tool này.

Hiện có **11 tool**: `lookup_part`, `search_parts`, `get_consumable_set`,
`find_upsell_companions`, `find_replacement`, `check_compatibility`,
`compare_parts`, `get_torches`, `get_troubleshoot`, `get_liner_length`,
`get_replacement_steps`.

Test tool độc lập (không qua LLM):

```python
from core.tool_wrappers import dispatch
print(dispatch("search_parts", {"query": "béc hàn", "top_k": 3}))
```

---

## 8. Eval

```bash
# Cần server đang chạy ở localhost:8080 + TOKINARC_API_KEY trong .env
python run_eval.py
# Đọc eval_700.json → gọi /api/v2/query từng case → ghi eval_fails.json, eval_summary.json
```

Báo cáo CSV ghi vào `logs/`. Xem `eval_summary.json` để biết tỉ lệ pass.

---

## 9. Quan hệ với backend (CRM/WMS/CEO)

Chatbot và Django backend là **2 service tách biệt**, không gọi nhau ở tầng code.
Chúng chỉ gặp ở nginx:
- `/api/chat/` → chatbot:8080
- `/api/` → django:8000

Chi tiết tích hợp + lưu ý auth header (nginx forward `Authorization` nhưng chatbot
cần `X-API-Key`): xem `docs/implementation/V6_MERGE_chatbot_real.md`.

---

## 10. Thư mục phụ

- `legacy/` — code pipeline cũ (v7), giữ tham khảo, không import.
- `archive_old/` — script một lần + data version cũ (v16-v18) + test cũ.
- `logs/` — query log + eval report (gitignore).
- `_smoke_test_orch.py`, `test_manual.py` — script test thủ công nhanh.
