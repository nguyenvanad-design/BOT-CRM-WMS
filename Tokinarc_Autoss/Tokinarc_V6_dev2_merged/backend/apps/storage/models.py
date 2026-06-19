"""
Tokinarc V6.C — apps/storage/models.py

FileObject metadata (B.2 §8). MinIO từ đầu → backend default 's3'. Nội dung file
ở MinIO; bảng này chỉ lưu metadata + key. sha256 để dedup.
"""
from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel


class FileObject(BaseModel):
    kind        = models.CharField(max_length=30, db_index=True)   # visit_photo/ticket_attach/vision/avatar
    filename    = models.CharField(max_length=255)
    mime_type   = models.CharField(max_length=80)
    size_bytes  = models.BigIntegerField()
    backend     = models.CharField(max_length=20, default='s3')    # MinIO từ đầu
    bucket      = models.CharField(max_length=63, default='tokinarc')
    path        = models.CharField(max_length=500)                 # S3 key
    sha256      = models.CharField(max_length=64, db_index=True)
    related_kind= models.CharField(max_length=40, blank=True)
    related_id  = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = 'storage_fileobject'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['related_kind', 'related_id'])]

    def __str__(self) -> str:
        return f"{self.filename} ({self.kind})"
