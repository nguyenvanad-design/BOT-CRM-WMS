"""
Tokinarc V6.C-fix — tokinarc/settings/production.py

Production phải set toàn bộ env biến rõ ràng. FAIL-LOUD: missing env raises
KeyError thay vì silent default.
"""
import os
from datetime import timedelta
from pathlib import Path

from .base import *

DEBUG = False
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']           # fail nếu thiếu
ALLOWED_HOSTS = os.environ['DJANGO_ALLOWED_HOSTS'].split(',')

DATABASES = {
    'default': {
        'ENGINE':   'django.db.backends.postgresql',
        'NAME':     os.environ['PGDATABASE'],
        'USER':     os.environ['PGUSER'],
        'PASSWORD': os.environ['PGPASSWORD'],
        'HOST':     os.environ['PGHOST'],
        'PORT':     os.environ.get('PGPORT', '5432'),
        'CONN_MAX_AGE': 60,
    }
}

# ─── Security ───────────────────────────────────────────────────────────────
CSRF_COOKIE_SECURE      = True
SESSION_COOKIE_SECURE   = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT     = True
SECURE_HSTS_SECONDS     = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# ─── CORS ───────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS    = os.environ['DJANGO_CORS_ORIGINS'].split(',')
CORS_ALLOW_CREDENTIALS  = True
CSRF_TRUSTED_ORIGINS    = os.environ['DJANGO_CSRF_TRUSTED'].split(',')

# ─── JWT — RS256 với Docker secrets ─────────────────────────────────────────
def _read_secret(path: str) -> str:
    return Path(path).read_text().strip()

_priv = os.environ.get('JWT_PRIVATE_KEY_PATH', '/run/secrets/jwt_private')
_pub  = os.environ.get('JWT_PUBLIC_KEY_PATH',  '/run/secrets/jwt_public')

SIMPLE_JWT['ALGORITHM']             = 'RS256'
SIMPLE_JWT['SIGNING_KEY']           = _read_secret(_priv)
SIMPLE_JWT['VERIFYING_KEY']         = _read_secret(_pub)
SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'] = timedelta(minutes=15)
SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']= timedelta(days=7)

# ─── Logging — structured JSON ──────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {'()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
                 'format': '%(asctime)s %(levelname)s %(name)s %(message)s'},
    },
    'handlers': {'json': {'class': 'logging.StreamHandler', 'formatter': 'json'}},
    'root':     {'handlers': ['json'], 'level': 'INFO'},
    'loggers':  {
        'django.security': {'handlers': ['json'], 'level': 'WARNING', 'propagate': False},
    },
}

# ─── Sentry (optional) ──────────────────────────────────────────────────────
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        environment=os.environ.get('SENTRY_ENV', 'production'),
    )
