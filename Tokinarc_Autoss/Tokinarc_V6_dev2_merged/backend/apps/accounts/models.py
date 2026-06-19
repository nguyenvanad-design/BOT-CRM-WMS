"""
Tokinarc V6.C — apps/accounts/models.py

User model. Role enum đến từ `apps.accounts.roles` (single source of truth) —
không define lại tại đây.
"""
from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models

from .roles import Role as _R, get_django_choices

# Backward-compat re-export — tests cũ import `from apps.accounts.models import Role`
Role = _R

# Lazy TextChoices — Django sẵn sàng khi file này import
RoleChoices = get_django_choices()


class User(AbstractUser):
    display_name = models.CharField(max_length=100, blank=True)
    phone        = models.CharField(max_length=20, blank=True)
    role         = models.CharField(max_length=20, choices=RoleChoices.choices,
                                    default=_R.SALES, db_index=True)
    # customer FK added in migration 0002 (tránh circular dep với crm)
    customer     = models.ForeignKey('crm.Customer', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='users')

    class Meta:
        db_table = 'accounts_user'

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"

    @property
    def is_manager(self) -> bool:
        from .roles import is_manager as _im
        return _im(self)
