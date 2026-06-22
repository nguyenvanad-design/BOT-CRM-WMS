"""Local-only settings: chạy nhanh bằng SQLite file (không cần Postgres).
KHÔNG commit/dùng cho prod. Dùng: DJANGO_SETTINGS_MODULE=tokinarc.settings.devlocal
"""
from .dev import *  # noqa

DATABASES['default'] = {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME':   str(BASE_DIR / 'devlocal.sqlite3'),
}

# Lead intake từ bot khách — khóa dev cố định (chỉ dùng local).
LEAD_INTAKE_KEY = 'dev-lead-intake-key'
