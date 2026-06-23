"""
Tokinarc V6.C-fix2 — apps/catalog/urls.py

Include vào tokinarc/urls.py:
    path('api/v1/catalog/', include('apps.catalog.urls')),
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .stock_availability import StockAvailabilityView
from .views import PartViewSet, TorchViewSet

router = DefaultRouter()
router.register(r'parts',   PartViewSet,   basename='part')
router.register(r'torches', TorchViewSet,  basename='torch')

urlpatterns = [
    # Bot khách: tình trạng còn hàng (thô, có key) — đặt trước router.
    path('stock-availability/', StockAvailabilityView.as_view(), name='stock-availability'),
] + router.urls
