"""Tokinarc V6.C-fix — tokinarc/settings/dev.py — local development."""
import os
from datetime import timedelta

from .base import *

DEBUG = True
SECRET_KEY = 'dev-only-not-for-production-do-not-use-in-prod'
ALLOWED_HOSTS = ['*']

# Khóa cho endpoint hẹp (lead-intake + stock-availability cho bot khách). Dev mặc định
# trùng chatbot/.env (CRM_INTAKE_KEY) để bot khách tra tồn được mà không cần export tay.
LEAD_INTAKE_KEY = os.getenv('LEAD_INTAKE_KEY', 'dev-lead-intake-key')

DATABASES = {
    'default': {
        'ENGINE':   'django.db.backends.postgresql',
        'NAME':     os.getenv('PGDATABASE', 'tokinarc'),
        'USER':     os.getenv('PGUSER',     'tokinarc'),
        'PASSWORD': os.getenv('PGPASSWORD', 'tokinarc'),
        'HOST':     os.getenv('PGHOST',     'localhost'),
        'PORT':     os.getenv('PGPORT',     '5432'),
    }
}

# Fallback SQLite cho test nhanh không cần postgres (chỉ khi không có PG env)
if not os.getenv('PGHOST') and os.getenv('USE_SQLITE') == '1':
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME':   ':memory:',
    }

CORS_ALLOW_ALL_ORIGINS = True
CSRF_TRUSTED_ORIGINS   = ['http://localhost:5173', 'http://localhost:8000']

# JWT — dev dùng HS256 với SECRET_KEY làm signing key (đơn giản)
SIMPLE_JWT['ALGORITHM']             = 'HS256'
SIMPLE_JWT['SIGNING_KEY']           = SECRET_KEY
SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'] = timedelta(minutes=60)   # dev: dài cho dễ test
SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']= timedelta(days=7)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root':     {'handlers': ['console'], 'level': 'INFO'},
}
