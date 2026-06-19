"""
Tokinarc V6.C — apps/common/models.py

Pattern cơ sở dùng chung cho mọi entity nghiệp vụ:
  - BaseModel:       id (UUID7), created_at/updated_at, created_by/updated_by
  - SoftDeleteMixin: deleted_at + deleted_by, manager filter mặc định
  - AuditLog:        append-only log mọi thay đổi (V6.A.2 §2)

UUID7: thư viện 'uuid6' cung cấp uuid7() — sort-by-time tự nhiên qua PK.
"""
from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db import models

try:
    from uuid6 import uuid7
except ImportError:
    # Fallback dùng uuid4 khi package chưa cài — dev environment
    def uuid7():
        return uuid.uuid4()


# ─── Managers ────────────────────────────────────────────────────────────────
class SoftDeleteManager(models.Manager):
    """Mặc định ẩn record đã xóa mềm. Dùng .with_deleted() để bao gồm."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

    def with_deleted(self):
        return super().get_queryset()

    def only_deleted(self):
        return super().get_queryset().filter(deleted_at__isnull=False)


# ─── Abstract base ───────────────────────────────────────────────────────────
class BaseModel(models.Model):
    """
    Kế thừa cho mọi entity nghiệp vụ. KHÔNG dùng cho catalog (PK string cố định)
    hoặc audit log (BigAuto là phù hợp).
    """
    id         = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='+', editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='+', editable=False,
    )

    class Meta:
        abstract = True
        get_latest_by = 'created_at'


class SoftDeleteMixin(models.Model):
    """Phối với BaseModel cho các entity cần audit/khôi phục."""
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='+',
    )

    objects     = SoftDeleteManager()
    all_objects = models.Manager()   # bypass filter

    class Meta:
        abstract = True

    def soft_delete(self, user=None) -> None:
        from django.utils import timezone
        self.deleted_at = timezone.now()
        if user is not None:
            self.deleted_by = user
        self.save(update_fields=['deleted_at', 'deleted_by'])

    def restore(self) -> None:
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['deleted_at', 'deleted_by'])


# ─── AuditLog ────────────────────────────────────────────────────────────────
class AuditLog(models.Model):
    """Append-only log. Không update, không delete."""
    id         = models.BigAutoField(primary_key=True)
    ts         = models.DateTimeField(auto_now_add=True, db_index=True)
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    action     = models.CharField(max_length=40, db_index=True)
    entity     = models.CharField(max_length=80, db_index=True)
    entity_id  = models.CharField(max_length=64, db_index=True)
    diff       = models.JSONField(default=dict, blank=True)
    via        = models.CharField(max_length=20, default='ui')  # ui|bot|api|cron
    ip         = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'common_audit_log'
        indexes  = [models.Index(fields=['entity', 'entity_id', '-ts'])]

    def __str__(self) -> str:
        return f"[{self.ts:%Y-%m-%d %H:%M}] {self.user} {self.action} {self.entity}#{self.entity_id}"

    @classmethod
    def record(cls, *, user, action: str, entity: str, entity_id: Any,
               diff: dict | None = None, via: str = 'ui',
               ip: str | None = None, user_agent: str = '') -> 'AuditLog':
        """Helper tiện gọi từ signal hoặc viewset."""
        return cls.objects.create(
            user=user if user and getattr(user, 'is_authenticated', False) else None,
            action=action, entity=entity, entity_id=str(entity_id),
            diff=diff or {}, via=via, ip=ip, user_agent=user_agent[:200],
        )
