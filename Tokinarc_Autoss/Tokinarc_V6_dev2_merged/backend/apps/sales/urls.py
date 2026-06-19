"""Tokinarc V6.C — apps/sales/urls.py"""
from rest_framework.routers import DefaultRouter
from .views import SalesOrderViewSet, PaymentViewSet

router = DefaultRouter()
router.register(r'orders', SalesOrderViewSet, basename='salesorder')
router.register(r'payments', PaymentViewSet, basename='payment')
urlpatterns = router.urls
