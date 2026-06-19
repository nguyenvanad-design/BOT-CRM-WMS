"""Tokinarc V6.C — apps/sales/permissions.py — refactor dùng accounts/roles.py."""
from rest_framework import permissions
from rest_framework.permissions import SAFE_METHODS

from apps.accounts.roles import MANAGER_ROLES, Role, role_of

WRITE_ROLES = frozenset({Role.SALES, Role.MANAGER, Role.ADMIN})


class SalesPermission(permissions.BasePermission):
    message = "Bạn không có quyền thao tác đơn bán."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated) or role_of(u) == Role.CUSTOMER:
            return False
        if request.method in SAFE_METHODS:
            return True
        return role_of(u) in WRITE_ROLES

    def has_object_permission(self, request, view, obj):
        r = role_of(request.user)
        if request.method in SAFE_METHODS:
            return r in MANAGER_ROLES or obj.owner_id == request.user.id
        return r in MANAGER_ROLES or obj.owner_id == request.user.id
