"""
Tokinarc V6.C-fix2 — apps/catalog/urls.py

Include vào tokinarc/urls.py:
    path('api/v1/catalog/', include('apps.catalog.urls')),
"""
from rest_framework.routers import DefaultRouter

from .views import PartViewSet, TorchViewSet

router = DefaultRouter()
router.register(r'parts',   PartViewSet,   basename='part')
router.register(r'torches', TorchViewSet,  basename='torch')

urlpatterns = router.urls
