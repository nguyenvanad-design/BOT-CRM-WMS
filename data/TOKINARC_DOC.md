# TOKINARC — Tài liệu kỹ thuật

**Hệ thống:** Chatbot tư vấn linh kiện hàn Tokinarc × Autoss VN  
**Eval:** 200/200 (100%) · 11/11 intent · p50=1.8s  
**Stack:** Python 3.11 · FastAPI · Gemini 2.5 Flash · FAISS

---

## Cấu trúc thư mục

```
botautoss/
├── main.py                          # FastAPI server — entry point duy nhất
├── vision_endpoint.py               # Vision routes (ngoài core/)
├── eval_700.py                      # Eval 200 case mới
├── eval_500.py                      # Eval 500 case base
├── eval_dashboard.py                # Tạo HTML report từ results JSON
├── core/
│   ├── pipeline_v7.py               # Pipeline chính — 3 layer
│   ├── llm_extractor.py             # Intent + entity extraction
│   ├── llm_explanation.py           # Gemini format response
│   ├── gemini_resilience.py         # Rate limit · retry · timeout
│   ├── session_store.py             # Multi-turn context (in-memory)
│   ├── system_prompts.py            # Tất cả prompts tập trung tại đây
│   ├── data_store.py                # Query handler 11 intent
│   ├── graph_traversal.py           # Graph UPSELL/CONSUMABLE_SET
│   ├── vector_index.py              # BGE-M3 + FAISS + CrossEncoder rerank
│   ├── bm25_search.py               # BM25 full-text fallback
│   ├── tokinarc_cer.py              # CER — compatibility engine
│   ├── assembly_kb.py               # Assembly knowledge base
│   ├── vision_module.py             # Gemini Vision phân tích ảnh
│   ├── query_logger.py              # JSONL observability logger
│   ├── structured_response.py       # P6 schema chuẩn cho frontend
│   ├── procedural_qa_retriever.py   # PQA retriever cho LLM polish
│   └── add_product.py               # Data update pipeline (scripts)
├── data/
│   ├── tokinarc_data_v12.json       # Parts · Torches · Consumable sets
│   └── assembly_procedures_v1_3.json # Install · Repair · Torque specs
└── indexes/
    ├── tokinarc_faiss.index         # FAISS vector index
    └── tokinarc_chunks.pkl          # Chunks metadata
```

---

## File-by-file

### `main.py` — Entry point
**Vai trò:** FastAPI server, khởi tạo tất cả modules, define endpoints.

**Endpoints:**
- `POST /api/v5/query` — query chính, trả `QueryResponse`
- `DELETE /api/v5/session/{id}` — xóa session
- `GET /api/v5/sessions/stats` — thống kê session
- `POST /api/v1/search` — vector search thuần
- `GET /api/v1/health` — health check
- `WS /ws/query` — WebSocket pipeline

**AppState** (singleton load khi startup):
```python
_state.cer            # TokinarcCER
_state.vector_index   # VectorIndex (BGE-M3 + FAISS)
_state.data_store     # TokinarcDataStore
_state.v5_extractor   # LLMExtractor (Gemini) hoặc RuleExtractor
_state.graph_traversal # GraphTraversal
_state.session_store  # SessionStore (in-memory)
_state.bm25_index     # BM25Index
_state.query_logger   # QueryLogger
```

**Chạy:** `python main.py` → `http://localhost:8000`  
**Auth:** Header `X-API-Key: dev-tokinarc-2026` (đổi qua env `TOKINARC_API_KEY`)

---

### `core/pipeline_v7.py` — Pipeline chính
**Vai trò:** Điều phối toàn bộ flow xử lý query. 3 layer:

```
PipelinePlanner.plan()     → PlanResult
PipelineExecutor.execute() → dict response
```

**Planner** quyết định (không gọi DB):
- Session inject + intent override
- Contradiction detection → early exit
- OUT_OF_SCOPE / LOW confidence → early exit
- Routing: use_graph, use_gemini

**Executor** thực thi:
- `_route_query()`: Tier1 Graph → Tier2 DataStore → Tier3 VectorIndex
- Recompute global confidence (P2)
- Format text (template hoặc Gemini)
- Update session

**Routing table:**
```
UPSELL          → GraphTraversal.resolve_upsell()
CONSUMABLE_SET  → GraphTraversal.get_full_consumable_set()
SEARCH_BY_DESC miss → VectorIndex.search() tier 3
*               → DataStore.query()
```

**Backward compat:** `run_v6 = run_v7`, `run_v5 = run_v7` — main.py không cần sửa.

---

### `core/llm_extractor.py` — Intent + Entity extraction
**Vai trò:** Nhận query → trả `ExtractionResult` (intent, confidence, entities).

**Flow:**
1. Pre-filter: greeting/terse → skip Gemini
2. `_deterministic_intent()` → rule-based patterns (bypass Gemini khi chắc chắn)
3. Nếu không match → `_extract_llm()` (Gemini 2.5 Flash, JSON mode)
4. Fallback: `RuleExtractor` nếu Gemini fail

**11 intent:** LOOKUP · SEARCH_BY_DESC · CONSUMABLE_SET · UPSELL · REPLACEMENT · COMPATIBILITY_CHECK · COMPARISON · AGGREGATE · INSTALLATION · REPAIR · OUT_OF_SCOPE

**Entities:** `part_nos`, `ecosystem` (N/D/WX/TIG), `current_class` (350A/500A...), `wire_size`, `categories`, `torch_models`, `owned_parts`, `filter_category`

**Quan trọng:** Mọi thay đổi prompt → sửa `system_prompts.py`, không sửa file này.

---

### `core/gemini_resilience.py` — Rate limit + Error handling
**Vai trò:** Bọc mọi Gemini call với retry + timeout + fallback message.

**API:**
```python
with_retry(fn, label="gemini_call")     # Retry 3 lần, backoff [1s, 3s, 7s]
fallback_error_response(query, ex, ...) # Response dict chuẩn khi fail hoàn toàn
fallback_text(ex)                       # Message tiếng Việt theo loại lỗi
```

**Exceptions:** `GeminiRateLimitError` (429) · `GeminiTimeoutError` · `GeminiUnavailableError` (5xx)

**Config:** `MAX_RETRIES=3`, `URLLIB_TIMEOUT=10s`, `BACKOFF_SECONDS=[1,3,7]`

---

### `core/data_store.py` — Query handler
**Vai trò:** Single source of truth cho data. Xử lý 11 intent → trả `{success, data, reason}`.

**Indexes built at startup:**
- `self.parts` — dict by tokin_part_no
- `self.p_alias / d_alias` — Panasonic/Daihen alias lookup
- `self.by_eco_cc` — filter by ecosystem+current_class
- `self.symptom_map` — troubleshooting từ assembly_procedures
- `self._text_index` — P3 text search fallback

**Field adapter:** `_repair()` và `_installation()` tự map field tiếng Anh của assembly_procedures (`symptom`, `likely_causes`, `action`) → field tiếng Việt mà template đọc (`symptom_vi`, `causes`, `actions`, `description_vi`).

**P3 text fallback:** Chỉ trigger khi có alias token (tipn, bechan, hr350...) hoặc thiếu full filter (eco+cc). Tránh false positive với query mô tả chung.

---

### `core/session_store.py` — Multi-turn context
**Vai trò:** Ghi nhớ context giữa các turn trong session.

**SessionContext lưu:**
- `last_intent`, `last_part_nos`, `last_ecosystem`, `last_current_class`
- `last_returned_parts` — top 5 parts đã trả

**inject_context():** Tự động inject vào e_dict khi:
- Query dùng pronoun ("cái này", "nó", "loại đó")
- Query là follow-up ngắn ("giá bao nhiêu", "còn loại nào")

**Config:** TTL=30min, MAX_SESSIONS=5000, LRU eviction.

---

### `core/graph_traversal.py` — Graph routing
**Vai trò:** Resolve UPSELL và CONSUMABLE_SET qua graph thay vì keyword filter.

**API:**
```python
graph.resolve_upsell(part_no)              # → UpsellResult
graph.get_full_consumable_set(torch, cc, eco) # → List[ConsumableSetResult]
```

Trả về companions kèm đầy đủ business fields (price_vnd, is_contact_price) để template hiển thị giá.

---

### `core/vector_index.py` — Semantic search
**Vai trò:** BGE-M3 embedding + FAISS + CrossEncoder rerank. Tier 3 fallback trong pipeline.

**Pipeline search:**
```
query → bge-m3 embed → FAISS top-40 → CrossEncoder rerank → top-10
```

**Config:** `MODEL_NAME="BAAI/bge-m3"`, `DEVICE="cuda"`, `RERANK_POOL_MULT=5`

**Build index:** `python core/vector_index.py --rebuild`

---

### `core/bm25_search.py` — BM25 full-text
**Vai trò:** Typo-tolerant search, tier 2.5 giữa DataStore và VectorIndex.

**Install:** `pip install rank-bm25`

**API:**
```python
idx = get_bm25_index(data_store._parts_list)  # singleton
results = idx.search("bec han 350A he N", eco="N", cc="350A", top_k=10)
```

---

### `core/query_logger.py` — Observability
**Vai trò:** Ghi JSONL log mỗi request để monitor production.

**Output:** `logs/queries.jsonl` — mỗi dòng:
```json
{"ts":"2026-05-24T06:00:00Z","intent":"SEARCH_BY_DESC","confidence":0.821,"latency_ms":1234.5,...}
```

**API:**
```python
logger = get_query_logger()
logger.log(result, query=q, session_id=sid)
logger.stats(last_n=1000)  # success_rate, avg_latency, intent_breakdown
```

Rotate tự động khi file > 50MB.

---

### `core/structured_response.py` — P6 Schema
**Vai trò:** Chuẩn hóa output cho frontend, tránh breaking change khi pipeline thay đổi.

**API:**
```python
from core.structured_response import from_pipeline
result = run_v7(query, ...)
response = from_pipeline(result)
return response.to_dict(include_debug=False)  # strip debug fields khi production
```

---

### `core/vision_module.py` — Vision analysis
**Vai trò:** Nhận ảnh linh kiện → Gemini Vision → structured result.

**Public API:**
```python
analyze_image(image_bytes, user_text)    # → dict (part_type, confidence, condition...)
confidence_level(result)                 # → "high" | "low" | "skip"
build_query(result, user_text)           # → str query cho pipeline
build_confirm_message(result, user_text) # → dict (text, confirm_needed)
extract_image_from_base64(b64)           # → bytes
extract_image_from_url(url)              # → bytes
has_image(platform, payload)             # → bool (Zalo/FB/WA)
extract_image(platform, payload)         # → bytes | None
```

Dùng `gemini_resilience.with_retry()` — không crash khi 429.

---

### `vision_endpoint.py` — Vision routes
**Vai trò:** Đăng ký 3 endpoint vision vào FastAPI app.

**Endpoints:**
- `POST /api/v1/vision` — Web UI / API direct
- `POST /api/v1/vision/webhook` — Forward từ Zalo/FB/WA
- `GET /api/v1/vision/health` — Health check

**Setup trong main.py:**
```python
from vision_endpoint import register_vision_routes
register_vision_routes(app)
```

Lấy `extractor`, `data_store` từ `app.state._state` qua property alias.

---

### `core/system_prompts.py` — Prompts
**Vai trò:** Tất cả LLM prompts tập trung tại đây. **Sửa prompt → sửa file này, không đụng logic.**

- `EXTRACTION_PROMPT` — dùng trong `llm_extractor.py`
- `ASSISTANT_PROMPT` — dùng cho conversation mode (V2, chưa active)
- `FORMATTER_PROMPT` — dùng trong `llm_explanation.py`

---

### `eval_dashboard.py` — Eval report
**Chạy:**
```bash
python eval_dashboard.py results_v7.json results_p3_v2.json --out dashboard.html
```

Tạo HTML với score trend chart, group breakdown, latency stats.

---

### `add_product.py` — Data update
**Chạy:**
```bash
python add_product.py --validate                    # Validate file hiện tại
python add_product.py --add part --file new.json    # Thêm parts mới
python add_product.py --add torch --file new.json   # Thêm torch mới
python add_product.py --dry-run --add part --file . # Preview không ghi
```

Tự động: backup → validate → version bump → nhắc chạy smoke test.

---

## Thêm intent mới

1. Thêm keyword vào `EXTRACTION_PROMPT` trong `system_prompts.py`
2. Thêm handler `_new_intent()` trong `data_store.py`
3. Thêm template format trong `pipeline_v7._template_format()`
4. Thêm vào `handlers` dict trong `data_store.query()`
5. Chạy eval confirm: `python eval_700.py --endpoint /api/v5/query --workers 3`

## Thêm data mới

```bash
python add_product.py --add part --file new_parts.json
python eval_700.py --endpoint /api/v5/query --out results_smoke.json --workers 2
```

## Env variables

| Var | Default | Mô tả |
|-----|---------|-------|
| `TOKINARC_API_KEY` | `dev-tokinarc-2026` | API key |
| `GEMINI_API_KEY` | — | Bắt buộc cho LLM mode |
| `TOKINARC_DATA` | `data/tokinarc_data_v12.json` | Data file |
| `TOKINARC_ASSEMBLY` | `data/assembly_procedures_v1_3.json` | Assembly file |
| `TOKINARC_LOG_DIR` | `logs/` | Query log directory |
| `TOKINARC_RERANK` | `1` | Bật/tắt CrossEncoder rerank |
| `TOKINARC_RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Rerank model |
