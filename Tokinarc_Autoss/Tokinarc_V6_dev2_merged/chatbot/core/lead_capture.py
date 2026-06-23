"""
core/lead_capture.py — Bot KHÁCH đẩy lead về CRM (ghi-1-chiều).

Chỉ GỬI thông tin liên hệ khách tự cung cấp tới endpoint intake của Django:
    POST {CRM_INTAKE_URL}  header X-Intake-Key: {CRM_INTAKE_KEY}
KHÔNG đọc bất kỳ dữ liệu CRM/WMS nào — giữ nguyên tắc tách 2 bot.

Cấu hình qua .env:
    CRM_INTAKE_URL=http://localhost:8000/api/v1/crm/lead-intake/
    CRM_INTAKE_KEY=dev-lead-intake-key
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger("tokinarc.lead_capture")

_URL = os.getenv("CRM_INTAKE_URL", "http://localhost:8000/api/v1/crm/lead-intake/")
_KEY = os.getenv("CRM_INTAKE_KEY", "")


def push_lead(name: str = "", phone: str = "", company: str = "",
              email: str = "", note: str = "") -> dict:
    """Gửi 1 lead sang CRM. Trả {ok, id?, error?}. Không raise ra ngoài."""
    if not _KEY:
        return {"ok": False, "error": "CRM_INTAKE_KEY chưa cấu hình"}
    if not (name or phone):
        return {"ok": False, "error": "Cần tên hoặc số điện thoại"}

    payload = json.dumps({
        "name": name, "phone": phone, "company": company,
        "email": email, "note": note,
    }).encode("utf-8")
    req = urllib.request.Request(
        _URL, data=payload, method="POST",
        headers={"Content-Type": "application/json", "X-Intake-Key": _KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            log.info("[lead_capture] pushed lead -> %s", body.get("id"))
            return {"ok": True, "id": body.get("id"), "name": body.get("name")}
    except urllib.error.HTTPError as e:
        log.warning("[lead_capture] HTTP %s: %s", e.code, e.reason)
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        log.warning("[lead_capture] error: %s", e)
        return {"ok": False, "error": str(e)}
