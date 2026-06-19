"""Tokinarc V6.C — apps/storage/urls.py"""
from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import UploadView, FileObjectViewSet
router = DefaultRouter()
router.register(r'files', FileObjectViewSet, basename='fileobject')
urlpatterns = [path('upload/', UploadView.as_view())] + router.urls
