"""Tokinarc — apps/purchasing/urls.py"""
from rest_framework.routers import DefaultRouter

from .views import (
    PurchaseOrderViewSet, PurchasePaymentViewSet, SupplierViewSet,
)

router = DefaultRouter()
router.register(r'suppliers', SupplierViewSet, basename='supplier')
router.register(r'orders', PurchaseOrderViewSet, basename='purchaseorder')
router.register(r'payments', PurchasePaymentViewSet, basename='purchasepayment')
urlpatterns = router.urls
