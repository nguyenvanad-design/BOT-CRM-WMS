"""Tokinarc V6 — ASGI entry (nếu cần async sau này)."""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tokinarc.settings.production')
application = get_asgi_application()
