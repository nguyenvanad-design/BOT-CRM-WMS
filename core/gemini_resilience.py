# core/gemini_resilience.py
# TOKINARC Gemini Resilience — retry, rate limit, timeout, fallback
# =================================================================
# Dùng bởi: llm_extractor.py, pipeline_v7.py
# UTF-8 NO BOM

from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

log = logging.getLogger("tokinarc.gemini_resilience")

T = TypeVar("T")

# ─── Custom Exceptions ────────────────────────────────────────────────────────

class GeminiRateLimitError(Exception):
    """Gemini trả 429 — rate limit / quota exceeded."""

class GeminiTimeoutError(Exception):
    """Gemini không trả lời trong thời gian cho phép."""

class GeminiUnavailableError(Exception):
    """Gemini trả 503 / 500 — service unavailable."""


# ─── Retry config ─────────────────────────────────────────────────────────────

_MAX_ATTEMPTS   = 3       # tổng số lần thử
_RETRY_DELAYS   = [1, 3]  # delay giữa các lần (seconds): attempt 1→2: 1s, 2→3: 3s
_TIMEOUT_S      = 10.0    # timeout mỗi lần gọi Gemini


# ─── with_retry ───────────────────────────────────────────────────────────────

def with_retry(fn: Callable[[], T], label: str = "gemini") -> T:
    """
    Gọi fn() với retry logic:
      - 429 (rate limit) → wait + retry
      - 503/500 (unavailable) → wait + retry
      - Timeout → retry
      - Sau MAX_ATTEMPTS → raise exception để caller fallback

    Usage:
        result = with_retry(
            fn=lambda: client.models.generate_content(...),
            label="llm_extractor",
        )
    """
    last_exc: Exception = RuntimeError("no attempts made")

    for attempt in range(_MAX_ATTEMPTS):
        try:
            return _call_with_timeout(fn, timeout=_TIMEOUT_S)

        except GeminiRateLimitError as e:
            last_exc = e
            if attempt < _MAX_ATTEMPTS - 1:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                log.warning(f"[{label}] Rate limit (429) attempt {attempt+1}/{_MAX_ATTEMPTS} "
                            f"— retry in {delay}s")
                time.sleep(delay)
            else:
                log.error(f"[{label}] Rate limit — all {_MAX_ATTEMPTS} attempts exhausted")

        except GeminiTimeoutError as e:
            last_exc = e
            if attempt < _MAX_ATTEMPTS - 1:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                log.warning(f"[{label}] Timeout attempt {attempt+1}/{_MAX_ATTEMPTS} "
                            f"— retry in {delay}s")
                time.sleep(delay)
            else:
                log.error(f"[{label}] Timeout — all {_MAX_ATTEMPTS} attempts exhausted")

        except GeminiUnavailableError as e:
            last_exc = e
            if attempt < _MAX_ATTEMPTS - 1:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                log.warning(f"[{label}] Unavailable (503) attempt {attempt+1}/{_MAX_ATTEMPTS} "
                            f"— retry in {delay}s")
                time.sleep(delay)
            else:
                log.error(f"[{label}] Unavailable — all {_MAX_ATTEMPTS} attempts exhausted")

        except Exception as e:
            # Lỗi khác (JSON parse, network...) — không retry
            log.warning(f"[{label}] Non-retryable error: {e}")
            raise

    raise last_exc


def _call_with_timeout(fn: Callable[[], T], timeout: float) -> T:
    """
    Chạy fn() với timeout.
    Dùng threading vì Gemini SDK không hỗ trợ async native timeout.
    """
    import threading

    result_box: list = [None]
    exc_box:    list = [None]

    def _target():
        try:
            result_box[0] = fn()
        except Exception as e:
            exc_box[0] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        # Thread vẫn chạy sau timeout
        log.warning(f"[gemini_resilience] Gemini call timed out after {timeout}s")
        raise GeminiTimeoutError(f"Gemini timeout after {timeout}s")

    if exc_box[0] is not None:
        _reclassify_and_raise(exc_box[0])

    return result_box[0]


def _reclassify_and_raise(exc: Exception) -> None:
    """
    Chuyển đổi exception từ Gemini SDK sang custom exception.
    google.api_core.exceptions.ResourceExhausted → GeminiRateLimitError
    google.api_core.exceptions.ServiceUnavailable → GeminiUnavailableError
    """
    exc_str  = str(exc).lower()
    exc_type = type(exc).__name__.lower()

    # Rate limit: 429, quota, resource exhausted
    if any(k in exc_str for k in ("429", "quota", "resource_exhausted", "rate limit",
                                   "ratelimit", "resourceexhausted")):
        raise GeminiRateLimitError(str(exc)) from exc

    if any(k in exc_type for k in ("resourceexhausted",)):
        raise GeminiRateLimitError(str(exc)) from exc

    # Service unavailable: 503, 500
    if any(k in exc_str for k in ("503", "500", "unavailable", "service unavailable",
                                   "internal server error")):
        raise GeminiUnavailableError(str(exc)) from exc

    if any(k in exc_type for k in ("serviceunavailable", "internalservererror")):
        raise GeminiUnavailableError(str(exc)) from exc

    # Timeout từ SDK
    if any(k in exc_str for k in ("timeout", "deadline", "timed out")):
        raise GeminiTimeoutError(str(exc)) from exc

    # Không phân loại được → re-raise nguyên
    raise exc


# ─── retry_http — dùng cho REST orchestrator (urllib) ────────────────────────
# FIX (restructure): trước đây OrchestratorV2REST._post gọi urllib trần,
# không retry khi Gemini trả 429/500/503. Helper này wrap call REST với
# retry + backoff, classify theo HTTP status code.

def retry_http(fn: Callable[[], T], label: str = "gemini_rest") -> T:
    """
    Retry cho REST call (urllib). fn() raise urllib.error.HTTPError/URLError.
      - 429            → GeminiRateLimitError   → retry
      - 500/502/503/504 → GeminiUnavailableError → retry
      - URLError/timeout → GeminiTimeoutError    → retry
      - 4xx khác (400, 401, 403...) → raise ngay, không retry
    """
    import urllib.error as _ue

    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return fn()
        except _ue.HTTPError as e:
            code = e.code
            if code == 429:
                last_exc = GeminiRateLimitError(f"HTTP 429: {e}")
            elif code in (500, 502, 503, 504):
                last_exc = GeminiUnavailableError(f"HTTP {code}: {e}")
            else:
                raise  # 400/401/403... — lỗi config/payload, retry vô ích
        except _ue.URLError as e:
            last_exc = GeminiTimeoutError(f"URLError: {e}")
        except TimeoutError as e:
            last_exc = GeminiTimeoutError(str(e))

        if attempt < _MAX_ATTEMPTS - 1:
            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
            log.warning(f"[{label}] {type(last_exc).__name__} attempt "
                        f"{attempt+1}/{_MAX_ATTEMPTS} — retry in {delay}s")
            time.sleep(delay)
        else:
            log.error(f"[{label}] all {_MAX_ATTEMPTS} attempts exhausted: {last_exc}")
    raise last_exc


# ─── fallback_error_response ─────────────────────────────────────────────────

def fallback_error_response(
    query: str,
    exc: Exception,
    session_id,
    latency_ms: float,
) -> dict:
    """
    Tạo response thân thiện khi Gemini hoàn toàn không phản hồi.
    Dùng bởi run_v7() trong pipeline_v7.py.
    """
    if isinstance(exc, GeminiRateLimitError):
        msg = ("Hệ thống đang bận, bạn vui lòng thử lại sau vài giây nhé ạ! "
               "Nếu cần gấp, anh/chị có thể mô tả linh kiện (mã, hệ N/D, dòng điện) "
               "để em hỗ trợ nhanh hơn 😊")
    elif isinstance(exc, GeminiTimeoutError):
        msg = ("Phản hồi hơi chậm lúc này, bạn thử lại ngay nhé ạ! "
               "Nếu biết mã linh kiện, anh/chị gõ thẳng mã để em tra nhanh hơn 😊")
    else:
        msg = ("Hệ thống tạm thời gián đoạn, bạn vui lòng thử lại sau ít phút ạ! "
               "Anh/chị có thể mô tả linh kiện cần tư vấn để em hỗ trợ 😊")

    log.warning(f"[gemini_resilience] fallback_error_response: {type(exc).__name__}: {exc}")

    return {
        "intent":              "OUT_OF_SCOPE",
        "query":               query,
        "text":                msg,
        "confidence":          0.0,
        "confidence_band":     "LOW",
        "needs_clarification": False,
        "clarification_q":     "",
        "session_id":          session_id or "",
        "success":             False,
        "parts":               [],
        "parts_count":         0,
        "latency_ms":          latency_ms,
        "mode":                "fallback_resilience",
        "match_type":          "none",
        "fallback_used":       True,
        "vision_used":         False,
        "vision_part_type":    "",
        "vision_confidence":   None,
        "vision_condition":    "",
        "vision_confirm_msg":  "",
        "vision_confirm_needed": False,
    }
