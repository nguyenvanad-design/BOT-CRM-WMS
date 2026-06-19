"""Tokinarc V6.C-fix — tokinarc/settings/test.py — luôn SQLite, isolated."""
from datetime import timedelta

from .base import *

DEBUG = False
SECRET_KEY = 'test-only-static-key-not-for-production-use-0123456789'
ALLOWED_HOSTS = ['*']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME':   ':memory:',
    }
}

CORS_ALLOW_ALL_ORIGINS = True

# MinIO bypass — test không gọi MinIO thật. services.save_upload() check
# `MINIO_ENDPOINT` rỗng → backend='local', không attempt connect.
MINIO_ENDPOINT = ''

# DRF — disable throttling trong test (mặc định 20/min anon → fail nhanh
# với test gọi liên tiếp).
REST_FRAMEWORK = {**REST_FRAMEWORK, 'DEFAULT_THROTTLE_CLASSES': []}

# JWT — test dùng HS256
SIMPLE_JWT['ALGORITHM']             = 'HS256'
SIMPLE_JWT['SIGNING_KEY']           = SECRET_KEY
SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'] = timedelta(minutes=60)
SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']= timedelta(days=1)

# Silence các log không cần
LOGGING = {'version': 1, 'disable_existing_loggers': True, 'handlers': {}, 'root': {'handlers': []}}
