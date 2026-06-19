"""Tokinarc V6 — WSGI entry (gunicorn)."""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tokinarc.settings.production')
application = get_wsgi_application()
