"""
Tokinarc V6 — apps/analytics/api_client.py

INTERNAL API CLIENT cho trợ lý nội bộ (assistant.py).

Mục tiêu: bot KHÔNG được đọc/ghi DB trực tiếp (không import model, không ORM).
Mọi thao tác phải đi QUA REST API — đúng tầng permission + serializer + audit như
frontend. Ở đây gọi API "in-process": dùng URL routing (django.urls.resolve) để tìm
đúng view, dựng request bằng APIRequestFactory + force_authenticate (danh tính =
chính nhân viên đang chat) rồi dispatch. Không đi qua HTTP/WSGI → nhanh, không phụ
thuộc server tự gọi chính nó, nhưng vẫn CHẠY QUA API (routing → view → quyền → serializer).

Dùng:
    from apps.analytics import api_client as apc
    data = apc.get(user, '/api/v1/analytics/revenue/monthly/')
    data = apc.get(user, '/api/v1/crm/customers/', query={'search': 'ABC'})
    data = apc.post(user, '/api/v1/crm/quotes/', {'customer': cid, 'lines': [...]})
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

_factory = APIRequestFactory()


class ApiError(Exception):
    """Lỗi khi gọi API nội bộ (status >= 400). Giữ status + body để tool xử lý."""

    def __init__(self, status: int, data):
        self.status = status
        self.data = data
        detail = ''
        if isinstance(data, dict):
            detail = str(data.get('detail') or data)
        elif data is not None:
            detail = str(data)
        self.detail = detail
        super().__init__(f"API {status}: {detail}")


def call(user, method: str, path: str, data=None, query: dict | None = None):
    """Gọi 1 endpoint REST nội bộ với danh tính `user`.

    path : đường dẫn tuyệt đối, vd '/api/v1/crm/quotes/' (KHÔNG kèm query string).
    query: dict → chèn vào query string cho GET/filter.
    data : body cho POST/PATCH/PUT.
    Trả về: body đã parse (dict/list) khi 2xx; raise ApiError khi >= 400.
    """
    method = method.lower()
    full = path
    if query:
        # bỏ các giá trị None để query gọn.
        q = {k: v for k, v in query.items() if v is not None}
        if q:
            full = f"{path}?{urlencode(q, doseq=True)}"

    factory_fn = getattr(_factory, method)
    if method in ('post', 'put', 'patch'):
        req = factory_fn(full, data=data or {}, format='json')
    else:
        req = factory_fn(full)
    force_authenticate(req, user=user)

    match = resolve(path)  # resolve theo path (không query) → view + args/kwargs
    resp = match.func(req, *match.args, **match.kwargs)
    if hasattr(resp, 'render'):
        resp.render()

    status = resp.status_code
    body = getattr(resp, 'data', None)
    if status >= 400:
        raise ApiError(status, body)
    return body


def get(user, path: str, query: dict | None = None):
    return call(user, 'get', path, query=query)


def post(user, path: str, data=None):
    return call(user, 'post', path, data=data)


def patch(user, path: str, data=None):
    return call(user, 'patch', path, data=data)


# ── Helpers phân trang: list endpoint DRF có thể trả {results,count} hoặc list thô ──
def results(body) -> list:
    """Chuẩn hóa body list endpoint → luôn trả list các item."""
    if isinstance(body, dict) and 'results' in body:
        return body['results'] or []
    if isinstance(body, list):
        return body
    return []


def count(body, fallback_list: list | None = None) -> int:
    """Tổng số bản ghi từ list endpoint (ưu tiên 'count' của phân trang)."""
    if isinstance(body, dict) and isinstance(body.get('count'), int):
        return body['count']
    return len(fallback_list if fallback_list is not None else results(body))
