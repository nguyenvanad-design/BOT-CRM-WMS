"""Tokinarc V6.C-fix — tokinarc/urls.py — root URL config."""
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView, SpectacularSwaggerView,
)

from apps.accounts.views import JWKSView
from tokinarc.health.views import live, ready

urlpatterns = [
    # ── Health (no auth) — Kubernetes/Compose probes ───────────────────
    path('api/health/live/',  live,  name='health-live'),
    path('api/health/ready/', ready, name='health-ready'),

    # ── OpenAPI ────────────────────────────────────────────────────────
    path('api/schema/',         SpectacularAPIView.as_view(),    name='schema'),
    path('api/docs/',           SpectacularSwaggerView.as_view(url_name='schema'),
                                                                  name='swagger'),

    # ── JWKS (no auth) cho FastAPI sidecar verify ──────────────────────
    path('.well-known/jwks.json', JWKSView.as_view(), name='jwks'),

    # ── App APIs ───────────────────────────────────────────────────────
    path('api/v1/auth/',      include('apps.accounts.auth_urls')),
    path('api/v1/accounts/',  include('apps.accounts.urls')),
    path('api/v1/catalog/',   include('apps.catalog.urls')),
    path('api/v1/crm/',       include('apps.crm.urls')),
    path('api/v1/wms/',       include('apps.wms.urls')),
    path('api/v1/sales/',     include('apps.sales.urls')),
    path('api/v1/analytics/', include('apps.analytics.urls')),
    path('api/v1/storage/',   include('apps.storage.urls')),
    path('api/v1/',           include('apps.common.urls')),
]
