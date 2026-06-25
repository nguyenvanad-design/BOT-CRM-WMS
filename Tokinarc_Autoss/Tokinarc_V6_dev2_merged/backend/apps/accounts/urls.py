"""
Tokinarc V6.C — apps/accounts/urls.py

tokinarc/urls.py:
    path('api/v1/auth/', include('apps.accounts.auth_urls')),
    path('api/v1/accounts/', include('apps.accounts.urls')),
    path('.well-known/jwks.json', JWKSView.as_view()),
"""
from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import AssignableEngineersView, UserViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
urlpatterns = router.urls + [
    path('engineers/', AssignableEngineersView.as_view(), name='engineers'),
]
