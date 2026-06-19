# Tokinarc V6.C-fix2 — Changelog

**Ngày fix**: 17/06/2026 (sau V6.C-fix cùng ngày)
**Phạm vi**: 3 BLOCKER + 2 BUG đã xác định trong đánh giá tổng thể V6.C-fix

## Tổng quan

Bộ V6.C-fix trước đó vững về kiến trúc và vaccine, nhưng còn 3 BLOCKER ngăn
`docker compose up` chạy được end-to-end. Bộ fix này gỡ cả 3:

**Kết quả test**: `pytest apps/ -q` → **59 passed** (45 cũ + 14 mới catalog) ✅
Không cần env var (`MINIO_ENDPOINT=''` đã set trong `settings/test.py`).

**Kết quả smoke test chatbot main.py V6**: 5/5 endpoint hoạt động đúng:
- `/api/v1/health/live` → 200
- `/api/v2/query` (no auth) → 422
- `/api/v2/query` (authed) → 200, trả stub response
- `/api/v2/query` (prompt injection) → 200, blocked=true
- `/api/v1/whoami` → 200, echo role chính xác

---

## BLOCKER đã fix

### BL1. Management command `run_eventbus_listener` (worker container CRASH)

**Vấn đề**: `infra/scripts/worker_entrypoint.sh` line 30 gọi
`python manage.py run_eventbus_listener` nhưng command không tồn tại trong
`apps/*/management/commands/`. Worker container vào loop crash-restart vô hạn.

**Fix**: Tạo file mới `backend/apps/common/management/commands/run_eventbus_listener.py`:
- Wrap `tokinarc.eventbus.listener.run_listener()`
- Auto-discover handler qua `apps/<app>/handlers.py` (theo pattern EXTENDING §5)
- Hỗ trợ `--channels=a,b,c` filter + `--poll-timeout` config
- Validate channel name khớp `ALL_CHANNELS`, fail-loud nếu typo

**Verify**:
```bash
$ python manage.py run_eventbus_listener --help        # → help OK
$ python manage.py run_eventbus_listener --channels=bogus  # → reject với message rõ
$ python manage.py run_eventbus_listener               # → "Không có handler" warning rồi exit
$ python manage.py run_eventbus_listener --channels=order_created  # → "Listener khởi với 1 channel" rồi bind LISTEN
```

### BL2. HTTP API cho catalog app (chatbot tool 404)

**Vấn đề**: `apps/catalog/` chỉ có `models.py + pricing.py`, không có
views/serializers/urls. `chatbot/tool_clients.py` gọi:
```
/api/v1/catalog/parts/search/
/api/v1/catalog/parts/{tokin_part_no}/
/api/v1/catalog/torches/{model_code}/
```
→ 404, bot không hoạt động được.

**Fix**: 3 file mới + wire vào root urls:
- `backend/apps/catalog/serializers.py` — Lite + Detail cho Part/Torch.
  Pricing đi qua `apps.catalog.pricing.get_effective_price()` (vaccine V2,
  single source). `price_display` format VND tiếng Việt.
- `backend/apps/catalog/views.py` — Read-only ViewSet:
  - `PartViewSet`: list/retrieve + `@action search` (ILIKE trên name/part_no/
    aliases P/D/O part_no, filter ecosystem/category, top_k≤50).
  - `TorchViewSet`: list/retrieve + `@action search` (ILIKE trên model_code/
    name/family).
  - `permission_classes = [AllowAny]` — catalog là public, khách Zalo tra cứu
    được.
- `backend/apps/catalog/urls.py` — DefaultRouter wire 2 ViewSet.
- `backend/tokinarc/urls.py` — thêm `path('api/v1/catalog/', ...)`.

**Endpoints sinh ra (verified bằng URL resolver)**:
```
/api/v1/catalog/parts/                       list
/api/v1/catalog/parts/{tokin_part_no}/       detail
/api/v1/catalog/parts/search/?q=...&top_k=10&ecosystem=P  search
/api/v1/catalog/torches/                     list
/api/v1/catalog/torches/{model_code}/        detail
/api/v1/catalog/torches/search/?q=...        search
```

**Test mới**: `backend/apps/catalog/tests/test_catalog_api.py` — 14 test cover:
- List + retrieve (Part, Torch)
- 404 cho part_no không tồn tại
- Search theo name VI, part_no, alias OEM (`P-NZ-350`)
- Search filter ecosystem + query ngắn (<2 ký tự) trả empty
- `is_contact_price=True` → `price_display='Liên hệ'`
- Endpoints public không cần JWT (5 case)

**Lưu ý**: Vector search semantic (BGE-M3 + pgvector) — TODO khi
`seed_embeddings.py` chạy. Hiện dùng ILIKE để bot hoạt động ngay.

### BL3. Chatbot main.py — viết lại V6 thuần (`core/*` missing)

**Vấn đề**: `chatbot/main.py` (1196 lines, v8.1.1) import 12 module từ `core/*`
(tokinarc_cer, vector_index, data_store, procedural_qa_retriever, bm25_reranker,
query_logger, graph_traversal, assembly_kb, tool_wrappers, session_store,
llm_orchestrator_v2, vision_module). Thư mục `core/` không có trong zip → chatbot
container ImportError ngay khi start.

**Fix**:
- Rename `chatbot/main.py` → `chatbot/main_legacy_v5.py` (giữ cho tham khảo,
  KHÔNG dùng làm entry).
- Tạo `chatbot/main.py` mới ~230 dòng theo kiến trúc V6 thuần:
  - Auth: `verify_jwt_dep` từ `auth_bridge.py` (JWKS verify)
  - Input guardrail: `check_input()` (prompt-injection + PII mask)
  - Tool dispatch: `dispatch_tool()` (role gate + Django REST proxy)
  - 6 route: `/api/v1/health/{live,ready}`, `/api/v1/whoami`,
    `/api/v2/query`, `/api/v5/query` (forward V2), `/api/v1/tool/dispatch`
- Refactor `chatbot/auth_bridge.py`: thêm `verify_jwt_with_raw_dep()` trả
  cả claims + raw token (tool dispatch cần raw để forward Authorization
  header sang Django REST).
- Đoạn LLM planning vẫn là stub (cần wire `google-genai` function calling) —
  nhưng pipeline còn lại (input guardrail, auth, response shape) đã hoạt
  động đúng. Smoke test 5 case xác nhận wiring sạch.

**TODO khi vào production**:
1. Wire Gemini function calling — thay block stub trong `query_v2()`:
   ```python
   tool_plan = await planner.decide(safe_msg, allowed_tools_for(role))
   if tool_plan.has_tool:
       result = await dispatch_tool(tool_plan.tool, tool_plan.payload, ctx)
       answer = await composer.compose(safe_msg, result)
   ```
2. WebSocket `/ws/query` cho streaming response (V5 đã có pattern, port sang).
3. Vector search endpoint `/api/v1/search` — gọi catalog parts/search/ qua
   tool_clients (sau khi seed embeddings).

---

## BUG đã fix

### B1. Storage tests fail trong môi trường sạch (README claim sai)

**Vấn đề**: `settings/test.py` không override `MINIO_ENDPOINT` → kế thừa
`'minio:9000'` từ `base.py` → `services.save_upload` cố `bucket_exists()` →
DNS fail → exception thoát ra → 3 storage tests FAILED.

**Fix**: Thêm 1 dòng `MINIO_ENDPOINT = ''` vào `settings/test.py`. Test pass
trong môi trường sạch không cần env var.

### B2. Throttling block test chạy nhiều endpoint (catalog tests)

**Vấn đề**: DRF default throttle `AnonRateThrottle: 20/min` block test gọi
endpoint catalog liên tiếp → 429.

**Fix**: `settings/test.py` thêm `REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES'] = []`.

### B3. `__import__('cryptography...')` xấu còn sót trong JWKSView

**Vấn đề**: V6.C-fix changelog claim đã loại bỏ `__import__` ở analytics,
nhưng vẫn còn pattern này ở `accounts/views.py` JWKSView (line 124–127).

**Fix**: Thay bằng `from cryptography.hazmat.primitives.serialization import
load_pem_public_key` import thường ở đầu hàm.

---

## File mới (BL fix)

| # | File | Vai trò |
|---|---|---|
| F1 | `backend/apps/common/management/__init__.py` | Package marker |
| F2 | `backend/apps/common/management/commands/__init__.py` | Package marker |
| F3 | `backend/apps/common/management/commands/run_eventbus_listener.py` | Worker entry command |
| F4 | `backend/apps/catalog/serializers.py` | Lite + Detail serializer |
| F5 | `backend/apps/catalog/views.py` | PartViewSet + TorchViewSet |
| F6 | `backend/apps/catalog/urls.py` | Router wire 2 ViewSet |
| F7 | `backend/apps/catalog/tests/__init__.py` | Package marker |
| F8 | `backend/apps/catalog/tests/test_catalog_api.py` | 14 test mới |
| F9 | `chatbot/main.py` | V6 thuần ~230 dòng |
| F10 | `docs/implementation/V6_C_5_Fix2_Changelog.md` | File này |

## File sửa

| # | File | Đổi gì |
|---|---|---|
| M1 | `backend/tokinarc/urls.py` | Thêm `path('api/v1/catalog/', include(...))` |
| M2 | `backend/tokinarc/settings/test.py` | `MINIO_ENDPOINT=''` + tắt throttling |
| M3 | `backend/apps/accounts/views.py` | Bỏ `__import__` xấu trong JWKSView |
| M4 | `chatbot/auth_bridge.py` | Thêm `verify_jwt_with_raw_dep()` |
| M5 | `chatbot/requirements.txt` | Cập nhật comment cho rõ V6 vs legacy |
| M6 | `chatbot/main.py` (rename) → `chatbot/main_legacy_v5.py` | Giữ legacy reference |

---

## Việc còn lại (sau V6.C-fix2)

Cho phép `docker compose up` chạy end-to-end với:
- Django backend serve 8 app HTTP (catalog đã có)
- Worker container run eventbus listener (không crash)
- Chatbot sidecar serve 6 endpoint V6 (input guardrail + auth + stub response)

Các việc tiếp **sau** fix2:

1. **CRM mở rộng**: Lead, Opportunity, Quote/QuoteLine, Visit, Activity,
   ServiceTicket, Warranty, InstalledMachine (~3-5 ngày). Khi có, các tool
   `create_quote`, `move_opportunity_stage`, `create_visit`, `create_ticket`
   trong `tool_clients.py` sẽ hoạt động (đang 404 với endpoint chưa code).
2. **Wire Gemini function calling** vào `chatbot/main.py` query_v2() — thay
   block stub bằng real LLM orchestration.
3. **`seed_embeddings.py`**: BGE-M3 → fill PartEmbedding.vector. Sau đó thay
   ILIKE search trong catalog/views.py bằng pgvector cosine.
4. **MV SQL migration** (B.2 §7): RunSQL CREATE MATERIALIZED VIEW.
5. **Event handler thật**: tạo `apps/<app>/handlers.py` + `apps.ready()` import
   để trigger `@subscribe` (theo EXTENDING §5).
6. **Frontend React code** (B.4 §8, ~4 tuần).

---

## Cách dùng

```bash
# 1. Giải nén
unzip Tokinarc_V6_fixed_complete.zip
cd Tokinarc_V6

# 2. Sinh JWT keys
bash infra/scripts/gen_keys.sh

# 3. Copy env
cp infra/.env.example .env
# Sửa: DJANGO_SECRET_KEY, PGPASSWORD, MINIO_*, GOOGLE_API_KEY...

# 4. Bring up
docker compose -f infra/docker-compose.yml --env-file .env up -d --build

# 5. Migrate + seed
docker compose -f infra/docker-compose.yml exec django python manage.py migrate
docker compose -f infra/docker-compose.yml exec django python manage.py seed_users_roles --admin-password=...
docker compose -f infra/docker-compose.yml exec django python manage.py seed_warehouse
docker compose -f infra/docker-compose.yml exec django python manage.py seed_from_json data/tokinarc_data_v19.json
```

Test local (SQLite, không cần Docker):
```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest apps/ -q
# → 59 passed
```
