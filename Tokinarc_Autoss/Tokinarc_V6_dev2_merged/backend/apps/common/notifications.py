"""
Tokinarc — apps/common/notifications.py
API thông báo trong app: mỗi user chỉ thấy thông báo của mình.
  GET  /api/v1/notifications/            — danh sách (mới nhất)
  GET  /api/v1/notifications/unread/     — {count}
  POST /api/v1/notifications/{id}/read/  — đánh dấu đã đọc
  POST /api/v1/notifications/read-all/   — đánh dấu tất cả đã đọc
"""
from __future__ import annotations

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'kind', 'message', 'link', 'is_read', 'created_at']
        read_only_fields = fields


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)[:50]

    @action(detail=False, methods=['get'])
    def unread(self, request):
        n = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({'count': n})

    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        Notification.objects.filter(pk=pk, user=request.user).update(is_read=True)
        return Response({'detail': 'ok'})

    @action(detail=False, methods=['post'], url_path='read-all')
    def read_all(self, request):
        n = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'detail': 'ok', 'updated': n})
