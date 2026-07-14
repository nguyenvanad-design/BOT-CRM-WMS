"""
TOKINARC API Server — v8.0
FastAPI | API Key auth | V2 Tool-Use pipeline chính

Endpoints:
  POST /api/v2/query          — Pipeline chính (Gemini function calling)
  POST /api/v5/query          — Backward compat → forward sang V2
  DELETE /api/v2/session/{id} — Xóa session
  DELETE /api/v5/session/{id} — Backward compat
  GET  /api/v2/sessions/stats — Session stats
  GET  /api/v5/sessions/stats — Backward compat
  POST /api/v1/search         — Vector search
  GET  /api/v1/health         — Health check
  WS   /ws/query              — WebSocket → V2
"""

from __future__ import annotations
import os
# FIX (restructure 2026-06): bỏ hardcode Windows path + force-override env var.
# Path resolution giờ ủy quyền hoàn toàn cho core.data_store:
#   env TOKINARC_DATA > auto-detect <repo>/data/tokinarc_data_v*.json (version cao nhất)

import asyncio
import base64
import collections
import json
import logging
import os
import secrets
import sys
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

# ── sys.path ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.resolve()
_CORE = _ROOT / "core"
for _p in [str(_ROOT), str(_CORE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Security, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

# ── Core imports ──────────────────────────────────────────────────────────────
from core.tokinarc_cer import TokinarcCER
from core.vector_index import VectorIndex

from dotenv import load_dotenv
load_dotenv(dotenv_path=_ROOT / ".env")
# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tokinarc.api")


# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════

API_KEY_NAME  = "X-API-Key"
_DEFAULT_DEV_KEY = "dev-tokinarc-2026"
VALID_API_KEY = os.getenv("TOKINARC_API_KEY", _DEFAULT_DEV_KEY)
GEMINI_KEY    = os.getenv("GEMINI_API_KEY", "")
APP_ENV       = os.getenv("TOKINARC_ENV", "dev").lower()   # dev | production

# FIX (restructure): fail-fast nếu production mà chưa set API key thật.
if APP_ENV == "production":
    if VALID_API_KEY == _DEFAULT_DEV_KEY:
        raise RuntimeError(
            "TOKINARC_ENV=production nhưng TOKINARC_API_KEY chưa được set "
            "(đang dùng default dev key). Set env var trước khi chạy."
        )
    if not GEMINI_KEY:
        raise RuntimeError("TOKINARC_ENV=production nhưng GEMINI_API_KEY chưa được set.")

# Data file — ủy quyền cho core.data_store (env > auto-detect version cao nhất)
from core.data_store import _resolve_data_path, _resolve_assembly_path
DATA_FILE     = _resolve_data_path()
ASSEMBLY_FILE = _resolve_assembly_path()


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic schemas
# ══════════════════════════════════════════════════════════════════════════════

class QueryRequestV2(BaseModel):
    """Request chính — V2 tool-use."""
    query:        str           = Field("", max_length=4096)
    session_id:   Optional[str] = Field(default=None)
    history:      list          = Field(default_factory=list,
                                       description="Conversation history [{role, parts}]")
    image_base64: Optional[str] = Field(default=None)
    image_url:    Optional[str] = Field(default=None,
                                        description="URL ảnh (Zalo/FB webhook)")
    platform:     Optional[str] = Field(default="api")


class QueryResponseV2(BaseModel):
    """Response V2."""
    text:         str
    tools_called: list          = []
    tool_results: list          = Field(default_factory=list)
    intent:       str           = ""
    entities:     dict          = Field(default_factory=dict)
    session_id:   Optional[str] = None
    success:      bool          = True
    latency_ms:   float         = 0.0
    model:        str           = ""
    vision_confirm_msg:    Optional[str] = None
    vision_confirm_needed: bool          = False


# Backward compat — V5 clients vẫn POST lên /api/v5/query với format này
class QueryRequest(BaseModel):
    query:        str           = Field("", max_length=4096)
    session_id:   Optional[str] = Field(default=None)
    image_base64: Optional[str] = Field(default=None)
    image_url:    Optional[str] = Field(default=None)
    platform:     Optional[str] = Field(default="api")


class QueryResponse(BaseModel):
    """Backward compat response shape cho V5 clients."""
    intent:              str
    query:               str
    text:                str
    confidence:          float
    confidence_band:     str
    needs_clarification: bool
    clarification_q:     Optional[str]   = None
    session_id:          Optional[str]   = None
    success:             bool            = False
    parts:               list            = []
    parts_count:         int             = 0
    latency_ms:          float           = 0.0
    mode:                str             = "v2_tool_use"
    vision_used:         bool            = False
    vision_part_type:    Optional[str]   = None
    vision_confidence:   Optional[float] = None
    vision_condition:    Optional[str]   = None
    vision_confirm_msg:  Optional[str]   = None
    vision_confirm_needed: bool          = False
    match_type:          str             = "exact"
    fallback_used:       bool            = False


class SearchRequest(BaseModel):
    query:           str   = Field(..., min_length=1, max_length=512)
    top_k:           int   = Field(default=5, ge=1, le=20)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    filter_type:     Optional[str] = Field(default=None)


class SearchResultItem(BaseModel):
    id:       str
    type:     str
    text:     str
    score:    float
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query:      str
    results:    list[SearchResultItem]
    total:      int
    latency_ms: float


class HealthResponse(BaseModel):
    status:        str
    engine_ready:  bool
    vector_ready:  bool
    v2_ready:      bool
    uptime_s:      float
    data_store_parts: int  = 0
    vector_count:  int     = 0
    bm25_ready:    bool    = False
    logger_ready:  bool    = False
    session_count: int     = 0
    gemini_key_set: bool   = False
    # Backward compat fields
    v5_ready:      bool    = False
    gemini_ready:  bool    = False
    formatter_ready: bool  = False


# ══════════════════════════════════════════════════════════════════════════════
# App state
# ══════════════════════════════════════════════════════════════════════════════

class AppState:
    cer:             Optional[TokinarcCER] = None
    vector_index:    Optional[VectorIndex] = None
    pqa:             Any = None
    started_at:      float = 0.0
    data_store:      Any = None
    graph_traversal: Any = None
    session_store:   Any = None
    orch_v2:         Any = None
    query_logger:    Any = None
    bm25_index:      Any = None
    assembly_kb:     Any = None   # AssemblyKB — assembly_procedures.json
    # Giữ lại để không NameError nếu code cũ reference
    v5_extractor:    Any = None
    gemini_model:    Any = None


_state = AppState()


# ══════════════════════════════════════════════════════════════════════════════
# Lifespan — khởi động / tắt
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    t0 = time.perf_counter()
    _state.started_at = time.time()
    log.info("🚀  TOKINARC API v8.0 starting up …")

    # ── DataStore ─────────────────────────────────────────────────────────────
    try:
        from core.data_store import get_data_store
        _state.data_store = get_data_store(DATA_FILE, ASSEMBLY_FILE)
        n = len(getattr(_state.data_store, "parts", {}))
        log.info(f"✅  DataStore ready — {n} parts ({DATA_FILE})")
    except Exception as e:
        log.warning(f"⚠️  DataStore failed: {e}")
        _state.data_store = None

    # ── CER (phải sau DataStore) ──────────────────────────────────────────────
    try:
        from core.tokinarc_cer import get_cer
        _state.cer = get_cer(ds=_state.data_store)
        log.info("✅  CER ready")
    except Exception as e:
        log.warning(f"⚠️  CER failed: {e}")
        _state.cer = None

    # ── VectorIndex ───────────────────────────────────────────────────────────
    try:
        _state.vector_index = VectorIndex(auto_build=False)
        n_vec = _state.vector_index._index.ntotal
        log.info(f"✅  VectorIndex ready — {n_vec} vectors")
        # Warmup
        for q in ("thân súng 500A hệ N", "tip 1.2mm 350A"):
            _ = _state.vector_index.search(q, top_k=3, filter_type="part")
        log.info("✅  Vector warmup done")
    except Exception as e:
        log.warning(f"⚠️  VectorIndex failed: {e}")
        _state.vector_index = None

    # ── PQA Retriever ─────────────────────────────────────────────────────────
    try:
        from core.procedural_qa_retriever import ProceduralQARetriever
        _state.pqa = ProceduralQARetriever.load(
            kb_path="data/procedural_qa_kb.jsonl",
            index_dir="indexes/procedural_qa_idx",
        )
        if _state.vector_index:
            _state.pqa.set_shared_model(_state.vector_index._get_model())
        log.info("✅  PQA Retriever ready")
    except Exception as e:
        log.warning(f"⚠️  PQA Retriever failed: {e}")
        _state.pqa = None

    # ── BM25 Reranker ─────────────────────────────────────────────────────────
    try:
        from core.bm25_reranker import get_bm25_reranker
        if _state.data_store:
            parts_list = getattr(_state.data_store, "_parts_list",
                                 list(getattr(_state.data_store, "parts", {}).values()))
            _state.bm25_index = get_bm25_reranker(parts_list=parts_list)
            log.info(f"✅  BM25 Reranker ready — {len(parts_list)} parts")
    except Exception as e:
        log.warning(f"⚠️  BM25 Reranker failed: {e}")
        _state.bm25_index = None

    # ── Query Logger ──────────────────────────────────────────────────────────
    try:
        from core.query_logger import get_query_logger
        _state.query_logger = get_query_logger()
        log.info("✅  QueryLogger ready → logs/queries.jsonl")
    except Exception as e:
        log.warning(f"⚠️  QueryLogger failed: {e}")
        _state.query_logger = None

    # ── GraphTraversal ────────────────────────────────────────────────────────
    try:
        from core.graph_traversal import get_graph_traversal
        _state.graph_traversal = get_graph_traversal(_state.cer)
        log.info("✅  GraphTraversal ready")
    except Exception as e:
        log.warning(f"⚠️  GraphTraversal failed: {e}")
        _state.graph_traversal = None

    # ── AssemblyKB — assembly_procedures.json ────────────────────────────────
    try:
        from core.assembly_kb import AssemblyKB
        _state.assembly_kb = AssemblyKB.from_file(ASSEMBLY_FILE)
        kb_stats = _state.assembly_kb.stats()
        log.info(
            f"✅  AssemblyKB ready — "
            f"ts={kb_stats.get('troubleshooting',0)} "
            f"procs={kb_stats.get('replacement_procedures',0)} "
            f"liners={kb_stats.get('liner_length_rows',0)} "
            f"torques={kb_stats.get('torque_specs',0)}"
        )
    except Exception as e:
        log.warning(f"⚠️  AssemblyKB failed: {e}")
        _state.assembly_kb = None

    # ── ToolWrappers — wire singletons ────────────────────────────────────────
    try:
        from core.tool_wrappers import (
            set_data_store, set_graph_traversal, set_cer,
            set_pqa, set_assembly_kb,
        )
        set_data_store(_state.data_store)
        set_graph_traversal(_state.graph_traversal)
        set_cer(_state.cer)
        set_pqa(_state.pqa)
        set_assembly_kb(_state.assembly_kb)
        log.info("✅  ToolWrappers wired (ds + gt + cer + pqa + kb)")
    except Exception as e:
        log.warning(f"⚠️  ToolWrappers wire failed: {e}")

    # ── SessionStore ──────────────────────────────────────────────────────────
    try:
        from core.session_store import get_session_store
        _state.session_store = get_session_store()
        backend = "Redis" if getattr(_state.session_store, "_redis_ok", False) else "in-memory"
        log.info(f"✅  SessionStore ready ({backend}, TTL=30min)")
    except Exception as e:
        log.warning(f"⚠️  SessionStore failed: {e}")
        _state.session_store = None

    # ── V2 Orchestrator ───────────────────────────────────────────────────────
    try:
        from core.llm_orchestrator_v2 import get_orchestrator
        _state.orch_v2 = get_orchestrator(api_key=GEMINI_KEY, force_rest=True)
        log.info(f"✅  OrchestratorV2 ready ({type(_state.orch_v2).__name__})")
    except Exception as e:
        log.warning(f"⚠️  OrchestratorV2 failed: {e}")
        _state.orch_v2 = None

    elapsed = (time.perf_counter() - t0) * 1000
    log.info(f"✅  All modules ready in {elapsed:.0f}ms")
    yield

    log.info("🛑  TOKINARC API shutting down")


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI app
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="TOKINARC Query API",
    description="Hệ thống tra cứu linh kiện hàn Tokinarc × Autoss — V2 Tool-Use",
    version="8.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    default_response_class=JSONResponse,
)

# FIX (restructure): CORS origins configurable — production nên set
#   TOKINARC_CORS_ORIGINS="https://app.autoss.vn,https://admin.autoss.vn"
_CORS_ORIGINS = [
    o.strip() for o in os.getenv("TOKINARC_CORS_ORIGINS", "*").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


class Utf8Middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        if "application/json" in response.headers.get("content-type", ""):
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response


app.add_middleware(Utf8Middleware)


# ── Custom 422 handler — log Pydantic ValidationError ra stderr ──────────────
# Bug fix 2026-06: default FastAPI không log 422 details → khó debug khi
# user gửi query quá dài. Handler này log tóm tắt + trả message tiếng Việt.

from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    errors = exc.errors()
    summary_parts = []
    for err in errors:
        loc = ".".join(str(x) for x in err.get("loc", []))
        msg = err.get("msg", "")
        ctx = err.get("ctx") or {}
        if "max_length" in ctx or "limit_value" in ctx:
            limit = ctx.get("max_length") or ctx.get("limit_value")
            summary_parts.append(f"{loc}: {msg} (limit={limit})")
        else:
            summary_parts.append(f"{loc}: {msg}")

    client_ip = request.client.host if request.client else "?"
    log.warning(
        f"[422] path={request.url.path} client={client_ip} "
        f"errors={'; '.join(summary_parts)}"
    )

    has_length_err = any(
        "length" in (e.get("msg") or "").lower() or "too long" in (e.get("msg") or "").lower()
        for e in errors
    )
    detail_vi = (
        "Nội dung quá dài. Vui lòng rút gọn câu hỏi (tối đa 4000 ký tự)."
        if has_length_err
        else "Yêu cầu không hợp lệ. Vui lòng kiểm tra lại định dạng."
    )
    return JSONResponse(
        status_code=422,
        content={"detail": detail_vi, "errors": errors, "success": False},
    )


# ── Rate Limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Per-IP rate limiter. Default 60 req/min. Gemini endpoints cost 3."""

    def __init__(self, limit: int = 60, window: int = 60):
        self._limit  = limit
        self._window = window
        self._counts: dict[str, collections.deque] = {}
        self._lock   = __import__("threading").Lock()
        self._last_prune = time.time()

    def _prune(self, now: float):
        """FIX (restructure 2026-06): dọn IP cũ — dict trước đây chỉ phình
        không bao giờ xóa (memory leak chậm với traffic scanner)."""
        if now - self._last_prune < 300:
            return
        self._last_prune = now
        cutoff = now - self._window
        stale = [ip for ip, dq in self._counts.items() if not dq or dq[-1] < cutoff]
        for ip in stale:
            del self._counts[ip]

    def is_allowed(self, ip: str, cost: int = 1) -> bool:
        now = time.time()
        with self._lock:
            self._prune(now)
            dq = self._counts.setdefault(ip, collections.deque())
            while dq and dq[0] < now - self._window:
                dq.popleft()
            if len(dq) + cost > self._limit:
                return False
            for _ in range(cost):
                dq.append(now)
            return True


_rate_limiter = RateLimiter(limit=int(os.getenv("RATE_LIMIT_RPM", "60")), window=60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    _GEMINI_PATHS = ("/api/v2/query", "/api/v5/query")

    # FIX (restructure): blacklist load từ env, code chỉ giữ default.
    # Production khuyến nghị chặn ở nginx/Cloudflare; đây là lớp phòng thủ phụ.
    #   TOKINARC_BLOCKED_SUBNETS="5.61.209.,93.123."  (comma-separated prefix)
    #   TOKINARC_BLOCKED_IPS="143.20.185.242"
    _DEFAULT_SUBNETS = ("5.61.209.", "93.123.", "187.191.", "209.38.", "133.175.")
    _DEFAULT_IPS     = ("143.20.185.242",)
    _BLOCKED_SUBNETS = tuple(
        s.strip() for s in
        os.getenv("TOKINARC_BLOCKED_SUBNETS", ",".join(_DEFAULT_SUBNETS)).split(",")
        if s.strip()
    )
    _BLOCKED_IPS = {
        s.strip() for s in
        os.getenv("TOKINARC_BLOCKED_IPS", ",".join(_DEFAULT_IPS)).split(",")
        if s.strip()
    }

    # Paths của scanner — block ngay
    _SCAN_PATHS = (
        "/.env", "/.git", "/.bash_history", "/config.yaml",
        "/SDK/", "/manager/", "/_next", "/wp-admin", "/phpmyadmin",
        "/.env.", "/config.", "/xmlrpc", "/cgi-bin", "/luci",
        "/setup.cgi", "/boaform", "/GponForm", "/shells",
    )

    @classmethod
    def _is_blocked(cls, ip: str) -> bool:
        if ip in cls._BLOCKED_IPS:
            return True
        return any(ip.startswith(subnet) for subnet in cls._BLOCKED_SUBNETS)

    async def dispatch(self, request: StarletteRequest, call_next):
        ip   = request.client.host if request.client else "unknown"
        path = request.url.path

        # Block scanner IPs/subnets
        if self._is_blocked(ip):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        # Block scan paths
        if any(path.startswith(p) for p in self._SCAN_PATHS):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        cost = 3 if any(path.startswith(p) for p in self._GEMINI_PATHS) else 1
        if not _rate_limiter.is_allowed(ip, cost=cost):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Vui lòng thử lại sau ít giây."},
                headers={"Retry-After": "10"},
            )
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)


# ── Auth ──────────────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def _key_ok(candidate) -> bool:
    """FIX (restructure): constant-time compare — chống timing attack."""
    if not isinstance(candidate, str):
        return False
    return secrets.compare_digest(candidate, VALID_API_KEY)


async def verify_api_key(api_key: str = Security(_api_key_header)) -> str:
    if not _key_ok(api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key


# ══════════════════════════════════════════════════════════════════════════════
# Vision helper — dùng chung cho REST và WS
# ══════════════════════════════════════════════════════════════════════════════

async def _process_image(
    image_base64: Optional[str],
    image_url: Optional[str],
    query: str,
) -> tuple[Optional[bytes], str, Optional[str], bool]:
    """
    Xử lý image input → (image_bytes, merged_query, confirm_msg, confirm_needed).
    Không raise — lỗi vision chỉ log warning, pipeline vẫn chạy với query gốc.
    """
    if not (image_base64 or image_url):
        return None, query, None, False

    image_bytes = None
    try:
        from core.vision_module import extract_image_from_base64, extract_image_from_url
        if image_base64:
            image_bytes = extract_image_from_base64(image_base64)
        elif image_url:
            image_bytes = extract_image_from_url(image_url)
    except Exception as e:
        log.warning(f"[vision] image intake failed: {e}")
        return None, query, None, False

    if not image_bytes:
        return None, query, None, False

    merged_query   = query
    confirm_msg    = None
    confirm_needed = False

    try:
        from core.vision_module import analyze_image, build_query, build_confirm_message
        vision_ctx = await asyncio.to_thread(analyze_image, image_bytes, query or None)
        if vision_ctx is not None:
            confirm_msg    = build_confirm_message(vision_ctx, query or None)
            confirm_needed = bool(getattr(vision_ctx, "confirm_needed", False))
            try:
                aug = build_query(vision_ctx, user_text=query or None)
                if aug:
                    merged_query = aug
            except Exception as e:
                log.warning(f"[vision] build_query failed: {e}")
    except Exception as e:
        log.warning(f"[vision] analyze_image failed: {e} — passing raw bytes to Gemini")

    return image_bytes, merged_query, confirm_msg, confirm_needed


# ══════════════════════════════════════════════════════════════════════════════
# REST — V2 (pipeline chính)
# ══════════════════════════════════════════════════════════════════════════════

router_v2 = APIRouter(prefix="/api/v2", tags=["v2"])


@router_v2.post("/query", response_model=QueryResponseV2)
async def query_v2(req: QueryRequestV2, _key: str = Depends(verify_api_key)):
    """
    Pipeline chính — Gemini function calling.
    LLM thấy full conversation, tự chọn tool, tổng hợp trả lời tiếng Việt.
    Support vision: image_base64 hoặc image_url.
    """
    if _state.orch_v2 is None:
        raise HTTPException(status_code=503, detail="V2 Orchestrator not ready")

    try:
        image_bytes, merged_query, confirm_msg, confirm_needed = await _process_image(
            req.image_base64, req.image_url, req.query or ""
        )

        result = await asyncio.to_thread(
            _state.orch_v2.run,
            query      = merged_query,
            session_id = req.session_id,
            history    = req.history or [],
            image_data = image_bytes,
        )

        _log_query(result, req.query, req.session_id, req.platform)

        return QueryResponseV2(
            text                   = result.text,
            tools_called           = result.tools_called,
            tool_results           = result.tool_results or [],
            intent                 = result.intent,
            entities               = result.entities or {},
            session_id             = req.session_id,
            success                = result.success,
            latency_ms             = float(result.latency_ms),
            model                  = result.model,
            vision_confirm_msg     = confirm_msg,
            vision_confirm_needed  = confirm_needed,
        )

    except HTTPException:
        raise
    except Exception as exc:
        log.error(f"[v2] error:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))


@router_v2.post("/stream")
async def stream_v2(req: QueryRequestV2, _key: str = Depends(verify_api_key)):
    """
    Streaming endpoint — Server-Sent Events (SSE).
    Planner chạy blocking, Responder stream từng chunk về client.

    Event format (text/event-stream):
      data: {"type":"tool_start","tool":"search_parts"}
      data: {"type":"tool_done","tool":"search_parts","ms":120}
      data: {"type":"text","chunk":"Dạ "}
      data: {"type":"done","intent":"SEARCH_BY_DESC","latency_ms":3200}
      data: {"type":"error","message":"..."}
    """
    if _state.orch_v2 is None:
        raise HTTPException(status_code=503, detail="V2 Orchestrator not ready")

    if not hasattr(_state.orch_v2, "stream_response"):
        raise HTTPException(status_code=501, detail="Streaming not supported by current orchestrator")

    async def event_generator():
        _collected_text   = []
        _collected_intent = ""
        _collected_tools  = []
        _collected_ent: dict = {}
        _t0 = time.perf_counter()
        try:
            gen = _state.orch_v2.stream_response(
                query      = req.query or "",
                session_id = req.session_id,
                history    = req.history or [],
            )
            for event in gen:
                # Thu thập data để log sau khi stream xong
                if event.get("type") == "text":
                    _collected_text.append(event.get("chunk", ""))
                elif event.get("type") == "done":
                    _collected_intent = event.get("intent", "")
                    _collected_ent = event.get("entities") or {}
                elif event.get("type") == "tool_start":
                    _collected_tools.append(event.get("tool", ""))
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            log.error(f"[stream_v2] error: {exc}")
            err = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(err)}\n\n"
        finally:
            # Ghi log sau khi stream hoàn tất
            if _state.query_logger:
                try:
                    class _FakeResult:
                        text        = "".join(_collected_text)
                        intent      = _collected_intent
                        tools_called= _collected_tools
                        tool_results= []
                        entities    = {}
                        success     = True
                        latency_ms  = round((time.perf_counter() - _t0) * 1000, 2)
                        model       = "gemini-2.5-flash"
                    _state.query_logger.log(
                        {
                            "intent":       _collected_intent,
                            "text":         "".join(_collected_text),
                            "latency_ms":   round((time.perf_counter() - _t0) * 1000, 2),
                            "tools_called": _collected_tools,
                            "success":      True,
                        },
                        query=req.query or "",
                        session_id=req.session_id,
                    )
                except Exception:
                    pass

            # Đẩy hội thoại về CRM (STREAMING — endpoint UI khách dùng). Non-blocking.
            # Kèm tên/SĐT nếu lượt này khách để lại liên hệ (capture_lead) → CRM link thread ↔ Lead.
            try:
                from core.conversation_logger import log_turn
                log_turn(session_key=req.session_id or "", user_text=req.query or "",
                         bot_text="".join(_collected_text), intent=_collected_intent,
                         channel=req.platform or "web",
                         customer_name=str(_collected_ent.get("name") or ""),
                         customer_phone=str(_collected_ent.get("phone") or ""))
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":  "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



router_v5 = APIRouter(prefix="/api/v5", tags=["v5-compat"])


@router_v5.post("/stream")
async def stream_v5(req: QueryRequest, _key: str = Depends(verify_api_key)):
    """V5 backward compat → forward sang V2 stream."""
    if _state.orch_v2 is None:
        raise HTTPException(status_code=503, detail="Orchestrator not ready")
    if not hasattr(_state.orch_v2, "stream_response"):
        raise HTTPException(status_code=501, detail="Streaming not supported")
    async def event_generator():
        _collected_text   = []
        _collected_intent = ""
        _collected_tools  = []
        _collected_ent: dict = {}
        _t0 = time.perf_counter()
        try:
            gen = _state.orch_v2.stream_response(
                query      = req.query or "",
                session_id = req.session_id,
                history    = [],
            )
            for event in gen:
                if event.get("type") == "text":
                    _collected_text.append(event.get("chunk", ""))
                elif event.get("type") == "done":
                    _collected_intent = event.get("intent", "")
                    _collected_ent = event.get("entities") or {}
                elif event.get("type") == "tool_start":
                    _collected_tools.append(event.get("tool", ""))
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            log.error(f"[stream_v5] error: {exc}")
            err = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(err)}\n\n"
        finally:
            if _state.query_logger:
                try:
                    _state.query_logger.log(
                        {
                            "intent":       _collected_intent,
                            "text":         "".join(_collected_text),
                            "latency_ms":   round((time.perf_counter() - _t0) * 1000, 2),
                            "tools_called": _collected_tools,
                            "success":      True,
                        },
                        query=req.query or "",
                        session_id=req.session_id,
                    )
                except Exception:
                    pass
            # Đẩy hội thoại về CRM (STREAMING v5). Non-blocking. Kèm tên/SĐT nếu có.
            try:
                from core.conversation_logger import log_turn
                log_turn(session_key=req.session_id or "", user_text=req.query or "",
                         bot_text="".join(_collected_text), intent=_collected_intent,
                         channel=req.platform or "web",
                         customer_name=str(_collected_ent.get("name") or ""),
                         customer_phone=str(_collected_ent.get("phone") or ""))
            except Exception:
                pass
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router_v5.post("/query", response_model=QueryResponse)
async def query_v5(req: QueryRequest, _key: str = Depends(verify_api_key)):
    """Backward compat — forward sang V2 pipeline, adapt response shape."""
    if _state.orch_v2 is None:
        raise HTTPException(status_code=503, detail="Orchestrator not ready")

    try:
        image_bytes, merged_query, confirm_msg, confirm_needed = await _process_image(
            req.image_base64, req.image_url, req.query or ""
        )

        result = await asyncio.to_thread(
            _state.orch_v2.run,
            query      = merged_query,
            session_id = req.session_id,
            history    = [],
            image_data = image_bytes,
        )

        _log_query(result, req.query, req.session_id, req.platform)

        return QueryResponse(
            intent               = result.intent or "LOOKUP",
            query                = req.query or "",
            text                 = result.text,
            confidence           = 1.0 if result.success else 0.3,
            confidence_band      = "HIGH" if result.success else "LOW",
            needs_clarification  = False,
            session_id           = req.session_id,
            success              = result.success,
            parts                = [],
            parts_count          = 0,
            latency_ms           = float(result.latency_ms),
            mode                 = "v2_tool_use",
            vision_confirm_msg   = confirm_msg,
            vision_confirm_needed = confirm_needed,
        )

    except HTTPException:
        raise
    except Exception as exc:
        log.error(f"[v5→v2] error:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))


@router_v5.delete("/session/{session_id}", status_code=204)
async def clear_v5_session(session_id: str, _key: str = Depends(verify_api_key)):
    if _state.session_store:
        _state.session_store.clear(session_id)


@router_v5.get("/sessions/stats")
async def session_stats_v5(_key: str = Depends(verify_api_key)):
    if _state.session_store is None:
        return {"status": "disabled"}
    return _state.session_store.stats()


# ══════════════════════════════════════════════════════════════════════════════
# REST — Utility
# ══════════════════════════════════════════════════════════════════════════════

router_util = APIRouter(prefix="/api/v1", tags=["utility"])


@router_util.post("/search", response_model=SearchResponse)
async def vector_search(req: SearchRequest, _key: str = Depends(verify_api_key)):
    """Vector search — BGE-M3 + FAISS."""
    t0 = time.perf_counter()
    if _state.vector_index is None:
        raise HTTPException(status_code=503, detail="VectorIndex not available")
    try:
        raw = _state.vector_index.search(
            req.query, top_k=req.top_k,
            filter_type=req.filter_type,
        )
        if req.score_threshold:
            raw = [r for r in (raw or []) if r.get("score", 0.0) >= req.score_threshold]
        results = [
            SearchResultItem(
                id=r.get("id", ""), type=r.get("type", ""),
                text=r.get("text", ""), score=round(r.get("score", 0.0), 4),
                metadata=r.get("metadata", {}),
            )
            for r in (raw or [])
        ]
        return SearchResponse(
            query=req.query, results=results, total=len(results),
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router_util.get("/health", response_model=HealthResponse)
async def health(_key: str = Depends(verify_api_key)):
    sess_count = 0
    if _state.session_store:
        try:
            sess_count = _state.session_store.stats().get("active_sessions", 0)
        except Exception:
            pass

    ds_parts = 0
    if _state.data_store:
        ds_parts = len(getattr(_state.data_store, "parts", {}))

    return HealthResponse(
        status           = "ok",
        engine_ready     = True,
        vector_ready     = _state.vector_index is not None,
        v2_ready         = _state.orch_v2 is not None,
        uptime_s         = round(time.time() - _state.started_at, 1),
        data_store_parts = ds_parts,
        vector_count     = getattr(getattr(_state.vector_index, "_index", None), "ntotal", 0),
        bm25_ready       = _state.bm25_index is not None,
        logger_ready     = _state.query_logger is not None,
        session_count    = sess_count,
        gemini_key_set   = bool(GEMINI_KEY),
        # Backward compat
        v5_ready         = _state.orch_v2 is not None,
        gemini_ready     = bool(GEMINI_KEY),
        formatter_ready  = _state.orch_v2 is not None,
    )


# ── Register routers ──────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# Live Traffic Monitor — GET /api/v2/traffic
# ══════════════════════════════════════════════════════════════════════════════

@router_v2.get("/traffic")
async def traffic_monitor(
    _key:       str = Depends(verify_api_key),
    n:          int = 20,
    session_id: str = "",
    intent:     str = "",
):
    """
    Xem N query gần nhất + stats nhanh.

    Params:
      n          — số query trả về (default 20, max 100)
      session_id — lọc 1 session cụ thể
      intent     — lọc theo intent (SEARCH_BY_DESC, LOOKUP, REPAIR...)

    Dùng nhanh trên terminal:

      # Windows PowerShell
      curl -H "X-API-Key: <key>" "http://localhost:8080/api/v2/traffic?n=20"

      # Live tail mỗi 3 giây
      while ($true) {
          curl -s -H "X-API-Key: <key>" "http://localhost:8080/api/v2/traffic?n=5"
          Start-Sleep 3
      }

      # Lọc theo session
      curl -H "X-API-Key: <key>" "http://localhost:8080/api/v2/traffic?session_id=abc123"

      # Lọc intent
      curl -H "X-API-Key: <key>" "http://localhost:8080/api/v2/traffic?intent=REPAIR"
    """
    import json as _json

    n        = min(n, 100)
    log_path = Path(os.getenv("TOKINARC_LOG_DIR", "logs")) / "queries.jsonl"

    if not log_path.exists():
        return JSONResponse({
            "rows": [], "total_in_file": 0,
            "note": "logs/queries.jsonl chưa có — server chưa nhận query nào",
        })

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()

    # Parse từ cuối lên (mới nhất trước), đọc tối đa 500 để filter + stats
    parsed = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            parsed.append(_json.loads(line))
        except Exception:
            continue
        if len(parsed) >= 500:
            break

    # Filter
    filtered = parsed
    if session_id:
        filtered = [r for r in filtered if r.get("session_id", "") == session_id]
    if intent:
        filtered = [r for r in filtered if r.get("intent", "") == intent]

    # Stats từ 200 dòng gần nhất (trước filter)
    recent   = parsed[:200]
    total_r  = len(recent)
    ok       = sum(1 for r in recent if r.get("success"))
    avg_lat  = (sum(r.get("latency_ms", 0) for r in recent) / total_r) if total_r else 0
    intents  = {}
    for r in recent:
        k = r.get("intent", "UNKNOWN")
        intents[k] = intents.get(k, 0) + 1

    # Rows trả về — trim field dài
    rows = []
    for r in filtered[:n]:
        rows.append({
            "ts":          r.get("ts", ""),
            "session_id":  r.get("session_id", "")[:8] + "…",
            "query":       r.get("query", "")[:120],
            "intent":      r.get("intent", ""),
            "success":     r.get("success", False),
            "latency_ms":  r.get("latency_ms", 0),
            "tools":       r.get("tools_called", []),
            "fallback":    r.get("fallback", False),
            "bot_preview": r.get("bot_response", "")[:120],
        })

    return JSONResponse({
        "total_in_file": len(lines),
        "returned":      len(rows),
        "stats_last_200": {
            "success_rate":      f"{ok/total_r*100:.1f}%" if total_r else "n/a",
            "avg_latency_ms":    round(avg_lat, 1),
            "intent_breakdown":  dict(sorted(intents.items(), key=lambda x: -x[1])),
        },
        "rows": rows,
    })


app.include_router(router_v2)
app.include_router(router_v5)
app.include_router(router_util)





# ── Chat UI ───────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def chat_ui():
    return FileResponse("vision_chat.html")


# ── Vision endpoints (external module) ───────────────────────────────────────

try:
    from vision_endpoint import register_vision_routes
    register_vision_routes(app)
    log.info("✅  Vision endpoints registered")
except Exception as _ve:
    log.warning(f"⚠️  Vision endpoint registration failed: {_ve}")


# ══════════════════════════════════════════════════════════════════════════════
# WebSocket — V2
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/query")
async def ws_query(websocket: WebSocket):
    """WebSocket — V2 tool-use pipeline."""
    await websocket.accept()
    try:
        data = await websocket.receive_json()

        if not _key_ok(data.get("api_key")):
            await websocket.send_json({"type": "error", "message": "Unauthorized"})
            await websocket.close(code=4001)
            return

        query_text   = str(data.get("query", "")).strip()
        session_id   = data.get("session_id")
        image_base64 = data.get("image_base64")
        image_url    = data.get("image_url")
        platform     = data.get("platform", "web")

        if not (query_text or image_base64 or image_url):
            await websocket.send_json({"type": "error", "message": "Empty query"})
            await websocket.close(code=4002)
            return

        if _state.orch_v2 is None:
            await websocket.send_json({"type": "error", "message": "Orchestrator not ready"})
            await websocket.close(code=4003)
            return

        await websocket.send_json({"type": "thinking"})

        image_bytes, merged_query, confirm_msg, confirm_needed = await _process_image(
            image_base64, image_url, query_text
        )

        result = await asyncio.to_thread(
            _state.orch_v2.run,
            query      = merged_query,
            session_id = session_id,
            history    = [],
            image_data = image_bytes,
        )

        _log_query(result, query_text, session_id, platform)

        await websocket.send_json({
            "type": "response",
            "data": {
                "text":                 result.text,
                "intent":               result.intent,
                "tools_called":         result.tools_called,
                "success":              result.success,
                "session_id":           session_id,
                "latency_ms":           result.latency_ms,
                "vision_confirm_msg":   confirm_msg,
                "vision_confirm_needed": confirm_needed,
                # Backward compat fields
                "needs_clarification":  False,
                "parts":                [],
            },
        })
        await websocket.send_json({"type": "done", "latency_ms": result.latency_ms})

    except WebSocketDisconnect:
        log.info("[ws] client disconnected")
    except Exception as exc:
        log.exception("[ws] error")
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _log_query(result: Any, query: str, session_id: Optional[str], channel: str = "web"):
    """Fire-and-forget query logger + đẩy hội thoại về CRM cho nhân viên xem/quản lý.
    `channel` = platform của request (web/zalo/facebook…) để CRM biết nguồn."""
    if _state.query_logger is not None:
        try:
            _state.query_logger.log(
                {
                    "intent":       getattr(result, "intent", ""),
                    "text":         getattr(result, "text", ""),
                    "latency_ms":   getattr(result, "latency_ms", 0),
                    "tools_called": getattr(result, "tools_called", []),
                    "success":      getattr(result, "success", False),
                },
                query=query, session_id=session_id,
            )
        except Exception:
            pass

    # Đẩy TỪNG LƯỢT hội thoại về CRM (non-blocking) → sale/quản lý xem trong app.
    try:
        from core.conversation_logger import log_turn
        ent = getattr(result, "entities", None) or {}
        log_turn(
            session_key=session_id or "",
            user_text=query or "",
            bot_text=getattr(result, "text", "") or "",
            intent=getattr(result, "intent", "") or "",
            channel=channel or "web",
            customer_name=str(ent.get("name") or ent.get("customer_name") or ""),
            customer_phone=str(ent.get("phone") or ent.get("customer_phone") or ""),
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
    )






