"""
Tokinarc V6.C — apps/accounts/services.py

Account lockout (B.6 §3.2): 5 lần login sai trong 15 phút → khóa 15 phút.
Đếm theo username+IP. Lưu Redis DB1; fallback in-memory dict khi không có Redis
(dev/test) để không phụ thuộc cứng.
"""
from __future__ import annotations

import time

MAX_FAILS = 5
WINDOW_SEC = 900  # 15 phút

try:
    import redis
    from django.conf import settings
    _r = redis.from_url(getattr(settings, 'REDIS_URL_RATELIMIT', 'redis://localhost:6379/1'))
    _r.ping()
    _BACKEND = 'redis'
except Exception:
    _r = None
    _BACKEND = 'memory'
    _mem: dict[str, tuple[int, float]] = {}   # key -> (count, first_ts)


def _key(username: str, ip: str) -> str:
    return f"login_fail:{username}:{ip}"


def record_fail(username: str, ip: str) -> int:
    k = _key(username, ip)
    if _BACKEND == 'redis':
        n = _r.incr(k)
        if n == 1:
            _r.expire(k, WINDOW_SEC)
        return int(n)
    count, first = _mem.get(k, (0, time.time()))
    if time.time() - first > WINDOW_SEC:
        count, first = 0, time.time()
    count += 1
    _mem[k] = (count, first)
    return count


def is_locked(username: str, ip: str) -> bool:
    k = _key(username, ip)
    if _BACKEND == 'redis':
        return int(_r.get(k) or 0) >= MAX_FAILS
    count, first = _mem.get(k, (0, 0.0))
    if time.time() - first > WINDOW_SEC:
        return False
    return count >= MAX_FAILS


def clear_fail(username: str, ip: str) -> None:
    k = _key(username, ip)
    if _BACKEND == 'redis':
        _r.delete(k)
    else:
        _mem.pop(k, None)
