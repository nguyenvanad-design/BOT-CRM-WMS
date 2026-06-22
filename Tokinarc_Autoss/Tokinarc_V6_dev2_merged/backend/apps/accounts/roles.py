"""
Tokinarc V6.C — apps/accounts/roles.py

**SINGLE SOURCE OF TRUTH cho Role + Hierarchy + Capabilities.**

Mọi file khác (permissions các app, guardrail chatbot, frontend role enum) PHẢI
import từ đây — không define lại. Khi thêm role mới, sửa duy nhất file này.

Ba tầng quy ước:
  1. ROLES         — danh sách role string hợp lệ
  2. ROLE_HIERARCHY— thứ tự ưu tiên (cao hơn = nhiều quyền hơn)
  3. CAPABILITIES  — quyền cụ thể từng role (write tool, read tool, admin)

Frontend đồng bộ qua: `python manage.py dump_roles > frontend/src/lib/auth/roles.ts`
(viết command dump_roles sau khi mở rộng).
"""
from __future__ import annotations


# ─── 1. Danh sách role hợp lệ ────────────────────────────────────────────────
class Role:
    CUSTOMER  = 'customer'
    SALES     = 'sales'
    WAREHOUSE = 'warehouse'
    SERVICE   = 'service'
    MANAGER   = 'manager'
    CEO       = 'ceo'
    ADMIN     = 'admin'


ALL_ROLES: frozenset[str] = frozenset({
    Role.CUSTOMER, Role.SALES, Role.WAREHOUSE,
    Role.SERVICE, Role.MANAGER, Role.CEO, Role.ADMIN,
})


# ─── 2. Hierarchy (so sánh quyền) ────────────────────────────────────────────
ROLE_HIERARCHY: dict[str, int] = {
    Role.CUSTOMER:  0,
    Role.SALES:     10,
    Role.WAREHOUSE: 10,
    Role.SERVICE:   10,
    Role.MANAGER:   50,
    Role.CEO:       70,
    Role.ADMIN:     100,
}

# CEO có toàn bộ quyền đọc/điều hành mức quản lý (đứng trên manager).
MANAGER_ROLES: frozenset[str] = frozenset({Role.MANAGER, Role.CEO, Role.ADMIN})

# Cấp duyệt 2 (báo giá vượt ngưỡng): chỉ CEO/admin.
CEO_ROLES: frozenset[str] = frozenset({Role.CEO, Role.ADMIN})


# ─── 3. Capabilities (write tools / read tools) ──────────────────────────────
# Khớp với chatbot/tool_guardrail.py — cập nhật cùng lúc.
WRITE_TOOL_REQUIREMENTS: dict[str, frozenset[str]] = {
    'create_quote':           frozenset({Role.SALES, Role.MANAGER, Role.CEO, Role.ADMIN}),
    'approve_quote':          frozenset({Role.MANAGER, Role.CEO, Role.ADMIN}),   # duyệt cấp 1
    'approve_quote_l2':       frozenset({Role.CEO, Role.ADMIN}),                 # duyệt cấp 2 (vượt ngưỡng)
    'quote_to_contract':      frozenset({Role.SALES, Role.MANAGER, Role.CEO, Role.ADMIN}),
    'move_opportunity_stage': frozenset({Role.SALES, Role.MANAGER, Role.CEO, Role.ADMIN}),
    'create_visit':           frozenset({Role.SALES, Role.MANAGER, Role.CEO, Role.ADMIN}),
    'create_ticket':          frozenset({Role.SALES, Role.SERVICE, Role.MANAGER, Role.CEO, Role.ADMIN}),
    'sign_order':             frozenset({Role.MANAGER, Role.CEO, Role.ADMIN}),
    'ship_order':             frozenset({Role.SALES, Role.WAREHOUSE, Role.MANAGER, Role.CEO, Role.ADMIN}),
    'create_payment':         frozenset({Role.MANAGER, Role.CEO, Role.ADMIN}),
    'wms_pick_confirm':       frozenset({Role.WAREHOUSE, Role.MANAGER, Role.CEO, Role.ADMIN}),
    'wms_adjust_inventory':   frozenset({Role.WAREHOUSE, Role.MANAGER, Role.CEO, Role.ADMIN}),
    'wms_transfer_stock':     frozenset({Role.WAREHOUSE, Role.MANAGER, Role.CEO, Role.ADMIN}),
}

# Read tools mọi authenticated role đều dùng được (không enforce role riêng).
READ_TOOLS: frozenset[str] = frozenset({
    'search_parts', 'get_part', 'get_torch',
    'get_customer', 'get_customer_360', 'list_customers',
    'get_inventory', 'get_serial_history',
    # Read tool tài chính/điều hành — enforce qua READ_TOOL_REQUIREMENTS bên dưới.
    'get_kpi_overview', 'get_revenue_monthly', 'get_revenue_by_segment',
    'get_debt_aging', 'get_inventory_value', 'get_pipeline_forecast',
    'get_purchasing_summary',
})

# ─── Bot nội bộ (analytics/assistant) — quyền theo intent ────────────────────
# Bot nội bộ KHÁC bot khách: chỉ nhân viên (role != customer) dùng được, và mỗi
# intent cần role tối thiểu. Customer KHÔNG bao giờ tới được đây (permission chặn).
INTERNAL_ROLES: frozenset[str] = frozenset(ALL_ROLES - {Role.CUSTOMER})

# Phạm vi BOT NỘI BỘ theo phòng ban (KHÁC quyền API/màn hình — chỉ áp cho chatbot):
#  - Sales: sale + cấp trên (manager/CEO/admin) — manager giám sát mảng sales.
#  - WMS:   warehouse + CEO/admin. Manager KHÔNG lập phiếu kho qua bot
#           (việc kho để nhân viên kho; chỉ CEO/admin toàn quyền liên phòng ban).
SALES_ROLES: frozenset[str] = frozenset({Role.SALES, Role.MANAGER, Role.CEO, Role.ADMIN})
WAREHOUSE_ROLES: frozenset[str] = frozenset({Role.WAREHOUSE, Role.CEO, Role.ADMIN})

ASSISTANT_INTENT_ROLES: dict[str, frozenset[str]] = {
    # Đọc nghiệp vụ tài chính/điều hành — manager/CEO/admin
    'revenue':            MANAGER_ROLES,
    'customer_debt':      MANAGER_ROLES,
    'top_customers':      MANAGER_ROLES,
    'dormant_customers':  MANAGER_ROLES,
    'ceo_report':         MANAGER_ROLES,
    'evaluate_plan':      MANAGER_ROLES,
    # Ghi nghiệp vụ — theo phòng ban (manager giám sát sales, KHÔNG làm kho)
    'create_quote':       SALES_ROLES,
    'create_contract':    SALES_ROLES,
    'wms_inbound':        WAREHOUSE_ROLES,
    'wms_outbound':       WAREHOUSE_ROLES,
    # Tra cứu tài liệu/sản phẩm Tokin — mọi nhân viên
    'lookup_doc':         INTERNAL_ROLES,
    # Đọc sâu
    'customer_orders':    SALES_ROLES,      # đơn/công nợ của 1 KH
    'stock_lookup':       INTERNAL_ROLES,   # tồn của 1 mã ở các kho
}


def can_use_intent(role: str, intent: str) -> bool:
    """True nếu role được phép dùng intent của bot nội bộ."""
    required = ASSISTANT_INTENT_ROLES.get(intent)
    return bool(required) and role in required


# Read tool NHẠY CẢM — đọc nhưng cần role tối thiểu (khớp analytics IsManagerOrAdmin).
# Tool đọc KHÔNG có trong dict này = mọi role nội bộ đọc được (vd get_inventory).
# Customer luôn bị chặn các tool nội bộ ở guardrail (xem tool_guardrail.py).
READ_TOOL_REQUIREMENTS: dict[str, frozenset[str]] = {
    'get_kpi_overview':        MANAGER_ROLES,
    'get_revenue_monthly':     MANAGER_ROLES,
    'get_revenue_by_segment':  MANAGER_ROLES,
    'get_debt_aging':          MANAGER_ROLES,
    'get_inventory_value':     MANAGER_ROLES,
    'get_pipeline_forecast':   MANAGER_ROLES,
    'get_purchasing_summary':  MANAGER_ROLES,
}


# ─── 4. Helpers ──────────────────────────────────────────────────────────────
def role_of(user) -> str:
    """Lấy role từ user object, fallback 'customer' an toàn."""
    return getattr(user, 'role', Role.CUSTOMER) or Role.CUSTOMER


def is_manager(user) -> bool:
    return role_of(user) in MANAGER_ROLES


def is_ceo(user) -> bool:
    """True nếu user đủ quyền duyệt cấp 2 (CEO/admin)."""
    return role_of(user) in CEO_ROLES


def has_role(user, *roles: str) -> bool:
    return role_of(user) in set(roles)


def can_write_tool(role: str, tool: str) -> bool:
    """True nếu role được phép gọi write tool."""
    if role == Role.CUSTOMER:
        return False
    required = WRITE_TOOL_REQUIREMENTS.get(tool)
    if required is None:
        return False   # tool chưa đăng ký → deny mặc định
    return role in required


def can_read_tool(role: str, tool: str) -> bool:
    """True nếu role được phép gọi read tool.

    - Customer: chỉ đọc tool catalog/sản phẩm công khai, KHÔNG đọc tool nội bộ.
    - Read tool nhạy cảm (trong READ_TOOL_REQUIREMENTS): cần đúng role tối thiểu.
    - Read tool nội bộ thường (vd get_inventory): mọi role nội bộ đọc được.
    """
    if tool not in READ_TOOLS:
        return False
    # Tool công khai cho khách: chỉ catalog/sản phẩm.
    customer_ok = {'search_parts', 'get_part', 'get_torch'}
    if role == Role.CUSTOMER:
        return tool in customer_ok
    required = READ_TOOL_REQUIREMENTS.get(tool)
    if required is None:
        return True   # read tool nội bộ thường → mọi role nội bộ OK
    return role in required


# ─── 5. TextChoices cho Django models ────────────────────────────────────────
# Tách khỏi `from django.db import models` để file này import được ở chatbot
# (không phụ thuộc Django setup).
def get_django_choices():
    """Lazy — chỉ gọi khi Django sẵn sàng (apps/accounts/models.py)."""
    from django.db import models

    class RoleChoices(models.TextChoices):
        CUSTOMER  = Role.CUSTOMER,  'Khách hàng'
        SALES     = Role.SALES,     'Sales'
        WAREHOUSE = Role.WAREHOUSE, 'Nhân viên kho'
        SERVICE   = Role.SERVICE,   'Kỹ sư dịch vụ'
        MANAGER   = Role.MANAGER,   'Quản lý'
        CEO       = Role.CEO,       'CEO'
        ADMIN     = Role.ADMIN,     'Admin'
    return RoleChoices
