"""Tokinarc V6.C — apps/sales/urls.py"""
from rest_framework.routers import DefaultRouter
from .views import InvoiceViewSet, PaymentViewSet, SalesOrderViewSet

router = DefaultRouter()
router.register(r'orders', SalesOrderViewSet, basename='salesorder')
router.register(r'payments', PaymentViewSet, basename='payment')
router.register(r'invoices', InvoiceViewSet, basename='invoice')
urlpatterns = router.urls
