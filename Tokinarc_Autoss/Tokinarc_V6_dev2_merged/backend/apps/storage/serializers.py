"""Tokinarc V6.C — apps/storage/serializers.py"""
from rest_framework import serializers
from .models import FileObject

class FileObjectSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    class Meta:
        model = FileObject
        fields = ['id','kind','filename','mime_type','size_bytes','backend',
                  'bucket','path','sha256','related_kind','related_id',
                  'download_url','created_at']
        read_only_fields = fields
    def get_download_url(self, obj):
        return f"/api/v1/storage/files/{obj.id}/download/"
