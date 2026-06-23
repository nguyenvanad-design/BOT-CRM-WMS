"""
core/stock_query.py — Bot KHÁCH hỏi TÌNH TRẠNG còn hàng (thô) từ CRM/WMS.

Chỉ READ tình trạng (Còn hàng/Sắp hết/Hết hàng/Liên hệ) — KHÔNG đọc số lượng
chính xác, kho, vị trí. Gọi endpoint hẹp của Django, có khóa X-Intake-Key.

Cấu hình .env:
    CRM_STOCK_URL=http://django:8000/api/v1/catalog/stock-availability/
    CRM_INTAKE_KEY=<trùng LEAD_INTAKE_KEY của Django>
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("tokinarc.stock_query")

_URL = os.getenv("CRM_STOCK_URL",
                 "http://localhost:8000/api/v1/catalog/stock-availability/")
_KEY = os.getenv("CRM_INTAKE_KEY", "")


def fetch_stock(part_nos: list[str]) -> dict[str, dict]:
    """Trả {part_no: {status, label, name}}. Rỗng nếu chưa cấu hình/khóa lỗi."""
    if not _KEY or not part_nos:
        return {}
    q = urllib.parse.urlencode({"parts": ",".join(part_nos[:50])})
    req = urllib.request.Request(f"{_URL}?{q}", method="GET",
                                 headers={"X-Intake-Key": _KEY})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {r["part"]: r for r in data.get("results", [])}
    except Exception as e:  # noqa: BLE001
        log.warning("[stock_query] error: %s", e)
        return {}
