"""
core/conversation_logger.py — Bot KHÁCH đẩy TỪNG LƯỢT hội thoại về CRM (ghi-1-chiều).

Cho phép sale/quản lý XEM & QUẢN LÝ hội thoại bot khách trong app. Non-blocking:
mỗi lượt gửi trên 1 thread daemon → KHÔNG thêm độ trễ cho câu trả lời của bot.
Giữ nguyên tắc tách 2 bot: chỉ GHI, không đọc dữ liệu nội bộ.

Cấu hình .env (tái dùng khóa của lead-intake):
    CRM_INTAKE_KEY=dev-lead-intake-key
    CRM_INTAKE_URL=http://localhost:8000/api/v1/crm/lead-intake/   # suy ra endpoint ingest
    CRM_CONV_URL=...            # (tùy chọn) ghi đè URL ingest hội thoại
    CRM_CONV_LOG=0             # đặt 0 để tắt
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request

log = logging.getLogger("tokinarc.conversation_logger")


def _default_url() -> str:
    base = os.getenv("CRM_INTAKE_URL", "http://localhost:8000/api/v1/crm/lead-intake/")
    return base.replace("lead-intake/", "bot-conversations/ingest/")


_URL = os.getenv("CRM_CONV_URL", "") or _default_url()
_KEY = os.getenv("CRM_INTAKE_KEY", "")
_ENABLED = os.getenv("CRM_CONV_LOG", "1") != "0"


def _post(payload: bytes) -> None:
    req = urllib.request.Request(
        _URL, data=payload, method="POST",
        headers={"Content-Type": "application/json", "X-Intake-Key": _KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=6):
            pass
    except urllib.error.HTTPError as e:      # 4xx/5xx: log nhẹ, không làm phiền bot
        log.debug("[conversation_logger] HTTP %s: %s", e.code, e.reason)
    except Exception as e:                   # noqa: BLE001 — không bao giờ raise ra bot
        log.debug("[conversation_logger] %s", e)


# Chuẩn hóa NGUỒN hội thoại: platform của request → channel gọn cho CRM.
_CHANNEL_MAP = {
    "api": "web", "web": "web", "website": "web",
    "zalo": "zalo", "zalo_oa": "zalo",
    "facebook": "facebook", "messenger": "facebook", "fb": "facebook",
    "whatsapp": "whatsapp", "wa": "whatsapp",
}


def _norm_channel(c: str) -> str:
    c = (c or "").lower().strip()
    return _CHANNEL_MAP.get(c, c or "web")


def log_turn(session_key: str, user_text: str = "", bot_text: str = "",
             channel: str = "web", intent: str = "",
             customer_name: str = "", customer_phone: str = "") -> None:
    """Gửi 1 lượt hội thoại (non-blocking). Bỏ qua nếu tắt / chưa có key / thiếu session.
    `channel` nhận platform của request (web/zalo/facebook/…) → chuẩn hóa cho CRM."""
    if not (_ENABLED and _KEY and session_key):
        return
    if not (user_text or bot_text):
        return
    payload = json.dumps({
        "session_key":    str(session_key)[:64],
        "channel":        _norm_channel(channel),
        "user_text":      user_text or "",
        "bot_text":       bot_text or "",
        "intent":         intent or "",
        "customer_name":  customer_name or "",
        "customer_phone": customer_phone or "",
    }).encode("utf-8")
    threading.Thread(target=_post, args=(payload,), daemon=True).start()
