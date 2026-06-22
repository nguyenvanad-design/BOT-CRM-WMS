"""Tokinarc — apps/common/urls.py"""
from rest_framework.routers import DefaultRouter

from .notifications import NotificationViewSet

router = DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='notification')
urlpatterns = router.urls
