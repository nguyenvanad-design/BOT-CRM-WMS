"""
Tokinarc V6.C-fix — apps/catalog/pricing.py

**SINGLE SOURCE OF TRUTH cho pricing logic.**

Mọi nơi cần biết "giá hiệu lực" của 1 Part/Torch phải gọi `get_effective_price()` —
KHÔNG đọc trực tiếp `part.price_vnd` ở serializer/view/service khác.

Hiện tại trả `part.price_vnd` (giá toàn cục). Khi mở rộng bảng `PriceList`
(giá theo KH/contract/qty), CHỈ sửa hàm này; mọi caller tự sáng.

Caller bắt buộc:
  - apps/sales/services.py    — line_total
  - apps/analytics/services.py— inventory_value
  - apps/crm/serializers.py   — quote line snapshot
  - chatbot/tool_clients.py   — bot trả giá cho khách
"""
from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from apps.catalog.models import Part, Torch
    from apps.crm.models import Customer


# ─── Public API ──────────────────────────────────────────────────────────────
def get_effective_price(
    item: 'Union[Part, Torch]',
    *,
    customer: 'Optional[Customer]' = None,
    qty: int = 1,
    on_date: 'Optional[_date]' = None,
) -> Decimal:
    """
    Trả giá hiệu lực (VND) cho 1 part/torch.

    Args:
        item:     Part hoặc Torch instance
        customer: KH (để tra contract price tương lai); hiện ignore
        qty:     Số lượng (cho tier pricing tương lai); hiện ignore
        on_date: Ngày tham chiếu (cho promo expiry tương lai); hiện ignore

    Returns:
        Decimal — giá VND. Decimal(0) nếu part không có giá.
    """
    # TODO khi có PriceList:
    #   1. Tìm contract price của customer (PriceList active, on_date in range)
    #   2. Áp dụng tier theo qty
    #   3. Fallback về part.price_vnd
    base = getattr(item, 'price_vnd', None)
    return Decimal(base) if base is not None else Decimal(0)


def is_contact_price(item: 'Union[Part, Torch]') -> bool:
    """True nếu cần liên hệ thay vì hiển thị số. Dùng cho UI + bot."""
    return bool(getattr(item, 'is_contact_price', False))


def format_price_vi(amount: Decimal) -> str:
    """Format VND tiếng Việt: 1500000 → '1.500.000 ₫'. Dùng cho text bot trả."""
    if amount is None:
        return 'Liên hệ'
    n = int(amount)
    s = f"{n:,}".replace(',', '.')
    return f"{s} ₫"


# ─── Helpers cho line item ──────────────────────────────────────────────────
def compute_line_total(qty: int, unit_price: Decimal, discount_pct: Decimal = Decimal(0)) -> Decimal:
    """Common formula — dùng ở Quote/SalesOrder/Outbound line."""
    gross = Decimal(qty) * Decimal(unit_price)
    disc  = gross * Decimal(discount_pct) / Decimal(100)
    return (gross - disc).quantize(Decimal('1'))
