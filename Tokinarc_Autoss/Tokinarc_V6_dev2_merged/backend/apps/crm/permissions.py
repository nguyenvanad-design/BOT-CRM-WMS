"""
Tokinarc V6.C — apps/crm/permissions.py

Refactor V6.C-fix: import Role + helpers từ `apps.accounts.roles` (single source).
KHÔNG còn define ROLE_HIERARCHY ở đây.
"""
from __future__ import annotations

from rest_framework import permissions
from rest_framework.permissions import SAFE_METHODS

from apps.accounts.roles import (
    ALL_ROLES, Role,
    is_manager, role_of,
)

WRITE_ROLES = frozenset({Role.SALES, Role.MANAGER, Role.CEO})   # admin = quản trị hệ thống, không làm nghiệp vụ


class IsAuthenticatedWithRole(permissions.BasePermission):
    message = "Bạn cần đăng nhập với một role hợp lệ."

    def has_permission(self, request, view) -> bool:
        u = request.user
        return bool(u and u.is_authenticated and role_of(u) in ALL_ROLES)


class CustomerPermission(permissions.BasePermission):
    """
    - GET/HEAD/OPTIONS: mọi authenticated role (queryset đã filter owner)
    - POST: sale, manager, admin
    - PATCH/PUT/DELETE: owner KH, hoặc manager/admin
    """
    message = "Bạn không có quyền thao tác KH này."

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return role_of(request.user) in WRITE_ROLES

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return is_manager(request.user) or obj.owner_id == request.user.id
        return is_manager(request.user) or obj.owner_id == request.user.id


def filter_customers_for_user(qs, user):
    """Manager+ xem hết; sale/service/warehouse chỉ KH của mình."""
    if is_manager(user):
        return qs
    return qs.filter(owner_id=user.id)
