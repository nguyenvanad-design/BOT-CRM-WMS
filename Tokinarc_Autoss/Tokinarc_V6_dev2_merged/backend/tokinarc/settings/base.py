"""
Tokinarc V6.C-fix — tokinarc/settings/base.py

Cấu hình chia sẻ giữa dev/staging/production. Mọi giá trị sensitive (SECRET_KEY,
DB password, etc.) lấy từ env trong `production.py`. `dev.py` có default ngắn
cho local.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ─── Apps ───────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'django_filters',
    'drf_spectacular',
    'corsheaders',

    'apps.common',
    'apps.catalog',
    'apps.accounts',
    'apps.crm',
    'apps.wms',
    'apps.sales',
    'apps.purchasing',
    'apps.analytics',
    'apps.storage',
    'apps.learning',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

ROOT_URLCONF = 'tokinarc.urls'
WSGI_APPLICATION = 'tokinarc.wsgi.application'
ASGI_APPLICATION = 'tokinarc.asgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS':    [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

# ─── Auth ───────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'accounts.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Locale ─────────────────────────────────────────────────────────────────
LANGUAGE_CODE = 'vi'
TIME_ZONE     = 'Asia/Ho_Chi_Minh'
USE_TZ        = True
USE_I18N      = True

# ─── DRF ────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_PAGINATION_CLASS':   'apps.common.pagination.DefaultPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_SCHEMA_CLASS':    'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {'user': '600/min', 'anon': '20/min'},
}

# ─── Upload (đính kèm AI nội bộ: ảnh/PDF/Excel) ─────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024   # 20MB (mặc định Django chỉ 2.5MB)
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# ─── JWT ────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ALGORITHM':              os.getenv('JWT_ALGORITHM', 'HS256'),
    'SIGNING_KEY':            os.getenv('JWT_SIGNING_KEY', ''),     # set ở production
    'VERIFYING_KEY':          os.getenv('JWT_VERIFYING_KEY', ''),
    'ACCESS_TOKEN_LIFETIME':  None,  # set ở dev.py/production.py
    'REFRESH_TOKEN_LIFETIME': None,
    'ROTATE_REFRESH_TOKENS':  True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUDIENCE':               os.getenv('JWT_AUDIENCE', 'tokinarc-api'),
    'ISSUER':                 os.getenv('JWT_ISSUER',   'tokinarc'),
    'JWT_KID':                os.getenv('JWT_KID',      'default'),
}

# ─── OpenAPI ────────────────────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    'TITLE':       'Tokinarc API',
    'DESCRIPTION': 'REST API cho CRM/WMS/Analytics (Phương án B).',
    'VERSION':     '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# ─── Static ─────────────────────────────────────────────────────────────────
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'static'

# ─── MinIO / file storage ───────────────────────────────────────────────────
MINIO_ENDPOINT   = os.getenv('MINIO_ENDPOINT',    'minio:9000')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY',  '')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY',  '')
MINIO_BUCKET     = os.getenv('MINIO_BUCKET',      'tokinarc-files')
MINIO_SECURE     = os.getenv('MINIO_SECURE', '0') == '1'

# ─── Redis (cache + rate limit + lockout) ───────────────────────────────────
REDIS_URL_CACHE     = os.getenv('REDIS_URL_CACHE',     'redis://redis:6379/0')
REDIS_URL_RATELIMIT = os.getenv('REDIS_URL_RATELIMIT', 'redis://redis:6379/1')

# ─── CRM — duyệt báo giá 2 cấp ──────────────────────────────────────────────
# Báo giá có total_vnd ≥ ngưỡng này cần duyệt cấp 2 (CEO) sau cấp 1 (manager).
QUOTE_L2_THRESHOLD_VND = int(os.getenv('QUOTE_L2_THRESHOLD_VND', '100000000'))
# Hạn hiệu lực báo giá mặc định (ngày) khi tạo nếu không nhập valid_until.
QUOTE_VALID_DAYS = int(os.getenv('QUOTE_VALID_DAYS', '30'))

# ─── Mua hàng — duyệt đơn mua 2 cấp ─────────────────────────────────────────
# Đơn mua có total_vnd ≥ ngưỡng này cần duyệt cấp 2 (CEO) sau cấp 1 (manager).
PO_L2_THRESHOLD_VND = int(os.getenv('PO_L2_THRESHOLD_VND', '100000000'))

# ─── Hợp đồng — duyệt 2 cấp ─────────────────────────────────────────────────
# Hợp đồng có value_vnd ≥ ngưỡng này cần duyệt cấp 2 (CEO) sau cấp 1 (manager).
CONTRACT_L2_THRESHOLD_VND = int(os.getenv('CONTRACT_L2_THRESHOLD_VND', '100000000'))

# ─── Hạn mức giảm giá (Báo giá / Hợp đồng) ──────────────────────────────────
# Duyệt theo % chiết khấu, KHÔNG theo giá trị:
#   - ≤ DISCOUNT_SALE_MAX_PCT     : quyền sale → tự động duyệt.
#   - ≤ DISCOUNT_MANAGER_MAX_PCT  : cần manager duyệt (cấp 1).
#   - >  DISCOUNT_MANAGER_MAX_PCT : cần CEO duyệt (cấp 2). CEO duyệt không giới hạn.
DISCOUNT_SALE_MAX_PCT    = float(os.getenv('DISCOUNT_SALE_MAX_PCT', '5'))
DISCOUNT_MANAGER_MAX_PCT = float(os.getenv('DISCOUNT_MANAGER_MAX_PCT', '10'))

# ─── Lead intake từ BOT KHÁCH (ghi-1-chiều) ─────────────────────────────────
# Bot khách gọi POST /api/v1/crm/lead-intake/ kèm header X-Intake-Key = giá trị này.
# Rỗng = TẮT cổng intake (mọi request bị 401). Đặt qua env ở production.
LEAD_INTAKE_KEY   = os.getenv('LEAD_INTAKE_KEY', '')
# Ngưỡng "sắp hết" khi bot khách hỏi tồn (trạng thái thô, không lộ số chính xác).
PUBLIC_LOW_STOCK_THRESHOLD = int(os.getenv('PUBLIC_LOW_STOCK_THRESHOLD', '10'))
# Username nhận lead mặc định; rỗng = sale đầu tiên (rồi admin) trong DB.
LEAD_INTAKE_OWNER = os.getenv('LEAD_INTAKE_OWNER', '')
