"""
Tokinarc V6.C-fix — tokinarc/health/views.py

Kubernetes-style probes. KHÔNG yêu cầu auth — orchestrator chỉ cần biết
process còn sống + dependency ready không.
"""
from __future__ import annotations

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET


@require_GET
@csrf_exempt
def live(request):
    """
    Liveness — process còn alive? Luôn 200 nếu Django chạy.
    Orchestrator dùng để biết khi nào cần restart container.
    """
    return JsonResponse({'status': 'alive'})


@require_GET
@csrf_exempt
def ready(request):
    """
    Readiness — sẵn sàng nhận traffic? Check DB connection.
    Trả 503 nếu DB down — orchestrator KHÔNG forward request.
    """
    checks = {}
    overall_ok = True

    # DB
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        checks['db'] = 'ok'
    except Exception as e:
        checks['db'] = f'fail: {e}'
        overall_ok = False

    # Redis (optional — không fail readiness nếu chỉ cache offline)
    try:
        import redis
        from django.conf import settings
        r = redis.from_url(getattr(settings, 'REDIS_URL_CACHE', 'redis://localhost:6379/0'),
                           socket_connect_timeout=1)
        r.ping()
        checks['redis'] = 'ok'
    except Exception as e:
        checks['redis'] = f'degraded: {e}'
        # không fail overall — Redis chỉ là cache

    payload = {'status': 'ready' if overall_ok else 'not_ready', 'checks': checks}
    return JsonResponse(payload, status=200 if overall_ok else 503)
