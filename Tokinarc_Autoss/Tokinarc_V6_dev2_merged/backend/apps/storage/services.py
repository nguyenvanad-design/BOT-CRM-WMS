"""
Tokinarc V6.C — apps/storage/services.py

save_upload() tính sha256 (dedup), đẩy lên MinIO, ghi FileObject. Nếu MinIO chưa
cấu hình (dev/test) → backend='local' lưu metadata, bỏ qua upload thực để code
chạy được. Production set MINIO_* env (B.5 §4.5).
"""
from __future__ import annotations

import hashlib

from django.conf import settings

from .models import FileObject


def _minio_client():
    try:
        from minio import Minio
        ep = getattr(settings, 'MINIO_ENDPOINT', None)
        if not ep:
            return None
        return Minio(ep, access_key=settings.MINIO_ACCESS_KEY,
                     secret_key=settings.MINIO_SECRET_KEY,
                     secure=getattr(settings, 'MINIO_SECURE', False))
    except Exception:
        return None


def save_upload(*, file, kind: str, related_kind='', related_id='', user=None) -> FileObject:
    data = file.read()
    sha = hashlib.sha256(data).hexdigest()

    existing = FileObject.objects.filter(sha256=sha).first()
    if existing:                       # dedup — trả file đã có
        return existing

    bucket = getattr(settings, 'MINIO_BUCKET', 'tokinarc')
    key = f"{kind}/{sha[:2]}/{sha}_{file.name}"
    client = _minio_client()
    backend = 's3'
    if client is not None:
        import io
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.put_object(bucket, key, io.BytesIO(data), length=len(data),
                          content_type=getattr(file, 'content_type', 'application/octet-stream'))
    else:
        backend = 'local'              # dev/test: không có MinIO

    return FileObject.objects.create(
        kind=kind, filename=file.name,
        mime_type=getattr(file, 'content_type', 'application/octet-stream'),
        size_bytes=len(data), backend=backend, bucket=bucket, path=key, sha256=sha,
        related_kind=related_kind, related_id=related_id,
        created_by=user, updated_by=user)
