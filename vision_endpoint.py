"""
vision_endpoint.py — Phase 4a TOKINARC Vision (v2)
HOOK pattern: dùng app.state._state.engine (instance đã load),
KHÔNG tạo QueryEngine() mới (tránh load bge-m3 lần 2).

THÊM vào main.py SAU dòng `app = FastAPI(...)`:
    from vision_endpoint import register_vision_routes
    register_vision_routes(app)
"""

from fastapi import APIRouter, Request, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from typing import Optional
import logging

# Load .env
try:
    from dotenv import load_dotenv
    from pathlib import Path as _P
    load_dotenv(_P(__file__).resolve().parent / ".env")
except ImportError:
    pass

logger = logging.getLogger(__name__)


def _get_main_state():
    """Lấy _state từ main.py (module-level singleton)."""
    try:
        import main as _main
        return getattr(_main, "_state", None)
    except Exception:
        return None

# Reuse API key auth từ main.py
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


# ── Request models ────────────────────────────────────────────────────────────
class VisionRequest(BaseModel):
    """Body cho /api/v1/vision (Web UI / API trực tiếp)."""
    image_base64: Optional[str] = None
    image_url:    Optional[str] = None
    user_text:    Optional[str] = None
    platform:     Optional[str] = "web"


class VisionWebhookRequest(BaseModel):
    """Body cho /api/v1/vision/webhook (forward từ Zalo/FB/WA handler)."""
    platform: str
    payload:  dict
    user_text: Optional[str] = None


# ── Auth helper (đồng bộ với main.py) ─────────────────────────────────────────
def _verify_api_key(api_key: str) -> bool:
    """Trùng logic main.py — kiểm X-API-Key."""
    import os
    expected = os.getenv("API_KEY", "dev-tokinarc-2026")
    return api_key == expected


# ── Core processor ────────────────────────────────────────────────────────────
async def _process_vision(
    image_bytes: bytes,
    user_text: Optional[str],
    platform: str,
    app_state,
) -> dict:
    """
    Pipeline: vision analyze → build query → reuse QueryEngine → confirm message.

    app_state = request.app.state._state  (TOKINARC singleton)
    """
    from core.vision_module import (
        analyze_image, build_query, build_confirm_message, confidence_level
    )

    # Step 1: Vision analyze
    vision_result = analyze_image(image_bytes, user_text=user_text)
    conf_level    = confidence_level(vision_result)

    # Step 2: Confirm message cho user
    confirm = build_confirm_message(vision_result, user_text=user_text)

    # Step 3: Build query text
    query_text = build_query(vision_result, user_text=user_text)

    # Step 4: Reuse pipeline run_v7 — không tạo engine mới
    qe_result = None
    if conf_level in ("high", "low") and query_text and app_state:
        try:
            from core.pipeline_v7 import run_v7
            # Lấy các dependencies từ app_state
            extractor      = getattr(app_state, "extractor", None)
            data_store     = getattr(app_state, "data_store", None)
            gemini_model   = getattr(app_state, "gemini_model", None)
            graph_traversal= getattr(app_state, "graph_traversal", None)
            session_store  = getattr(app_state, "session_store", None)

            if extractor and data_store:
                qe_result = run_v7(
                    query=query_text,
                    extractor=extractor,
                    data_store=data_store,
                    gemini_model=gemini_model,
                    graph_traversal=graph_traversal,
                    session_store=session_store,
                )
            else:
                logger.warning("[VisionEndpoint] app_state missing extractor or data_store")
        except Exception as e:
            logger.warning(f"[VisionEndpoint] run_v7 error: {e}", exc_info=True)
            qe_result = {"error": str(e)}

    response = {
        "platform":         platform,
        "confidence_level": conf_level,
        "confidence_score": vision_result.get("confidence", 0.0),
        "part_type":        vision_result.get("part_type"),
        "part_label":       confirm.get("part_label"),
        "condition":        vision_result.get("condition"),
        "brand_hint":       vision_result.get("brand_hint"),
        "size_hint":        vision_result.get("size_hint"),
        "damage_detail":    vision_result.get("damage_detail"),
        "confirm_message":  confirm["text"],
        "confirm_needed":   confirm["confirm_needed"],
        "query_used":       query_text,
        "query_result":     qe_result,
    }

    logger.info(
        f"[VisionEndpoint] platform={platform} "
        f"part={vision_result.get('part_type')} "
        f"conf={conf_level} "
        f"query='{query_text[:60]}'"
    )
    return response


# ── Register routes vào FastAPI app ───────────────────────────────────────────
def register_vision_routes(app):
    """
    Đăng ký router vision vào FastAPI app.
    Gọi 1 lần trong main.py sau khi `app = FastAPI(...)`.
    """
    router = APIRouter(prefix="/api/v1", tags=["vision"])

    @router.post("/vision")
    async def vision_query(
        body: VisionRequest,
        request: Request,
        api_key: str = Security(API_KEY_HEADER),
    ):
        """Endpoint Web UI / API direct."""
        if not _verify_api_key(api_key):
            raise HTTPException(status_code=401, detail="Invalid API key")

        from core.vision_module import (
            extract_image_from_base64, extract_image_from_url
        )

        image_bytes = None
        if body.image_base64:
            image_bytes = extract_image_from_base64(body.image_base64)
        elif body.image_url:
            image_bytes = extract_image_from_url(body.image_url)

        if not image_bytes:
            raise HTTPException(status_code=400, detail="No valid image provided")

        app_state = _get_main_state()
        return await _process_vision(
            image_bytes, body.user_text, body.platform or "web", app_state
        )

    @router.post("/vision/webhook")
    async def vision_webhook(
        body: VisionWebhookRequest,
        request: Request,
        api_key: str = Security(API_KEY_HEADER),
    ):
        """Endpoint forward từ Zalo/FB/WA webhook handlers."""
        if not _verify_api_key(api_key):
            raise HTTPException(status_code=401, detail="Invalid API key")

        from core.vision_module import extract_image, has_image

        if not has_image(body.platform, body.payload):
            return {"has_image": False, "message": None}

        image_bytes = extract_image(body.platform, body.payload)
        if not image_bytes:
            return {"has_image": True, "error": "Could not download image"}

        app_state = _get_main_state()
        return await _process_vision(
            image_bytes, body.user_text, body.platform, app_state
        )

    @router.get("/vision/health")
    async def vision_health(request: Request):
        """Health check cho vision module."""
        import os
        app_state = _get_main_state()
        return {
            "vision_module":  "ready",
            "gemini_api_key": bool(os.getenv("GEMINI_API_KEY", "")),
            "query_engine":   app_state is not None and getattr(app_state, "engine", None) is not None,
            "prompts": ["part_id", "torch_id", "damage_check", "component_locate"],
        }

    app.include_router(router)
    logger.info("✅  Vision routes registered: /api/v1/vision, /api/v1/vision/webhook, /api/v1/vision/health")
