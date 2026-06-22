"""
Tokinarc V6.C — apps/wms/permissions.py

Refactor V6.C-fix: dùng Role + helpers từ `apps.accounts.roles`. KHÔNG redefine.
  - "đọc rộng, ghi hẹp": mọi role nội bộ đọc được tồn kho; chỉ warehouse +
    manager + admin được ghi (adjust/transfer/inbound/outbound).
  - customer KHÔNG được chạm WMS (internal gateway đã chặn, đây là tầng 2).
"""
from __future__ import annotations

from rest_framework import permissions
from rest_framework.permissions import SAFE_METHODS

from apps.accounts.roles import INTERNAL_ROLES, WMS_OP_ROLES, Role, role_of

# Đọc: mọi nhân viên (trừ customer). Ghi nghiệp vụ: WMS_OP_ROLES.
WMS_READ_ROLES  = INTERNAL_ROLES
WMS_WRITE_ROLES = WMS_OP_ROLES          # nhập/xuất/chuyển/quét/đếm (gồm nhân viên kho)
# Kiểm soát tồn (điều chỉnh/duyệt kiểm kê/FIFO-FEFO): WMS_CONTROL_ROLES (ko cho NV kho).


class WmsAccess(permissions.BasePermission):
    message = "Bạn không có quyền truy cập WMS."

    def has_permission(self, request, view) -> bool:
        u = request.user
        if not (u and u.is_authenticated):
            return False
        r = role_of(u)
        if r == Role.CUSTOMER:
            return False
        if request.method in SAFE_METHODS:
            return r in WMS_READ_ROLES
        return r in WMS_WRITE_ROLES

# Backward-compat alias — views.py + tests cũ dùng tên WMSPermission
WMSPermission = WmsAccess
