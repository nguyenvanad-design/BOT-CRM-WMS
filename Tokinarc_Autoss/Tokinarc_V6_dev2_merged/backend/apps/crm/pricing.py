"""
Tokinarc — apps/crm/pricing.py
Gợi giá theo PHÂN KHÚC khách (PriceTier) + tồn KHẢ DỤNG cho form báo giá/đơn.
Chỉ gợi ý — sale vẫn sửa tay được.
"""
from __future__ import annotations

from django.db.models import F, Sum


def tier_discount(segment: str) -> float:
    """% chiết khấu của phân khúc (0 nếu không có)."""
    from .models import PriceTier
    if not segment:
        return 0.0
    t = PriceTier.objects.filter(segment=segment).first()
    return float(t.discount_pct) if t else 0.0


def suggested_unit_price(list_price: int, segment: str) -> int:
    """Giá đề xuất = giá niêm yết × (1 − chiết khấu phân khúc)."""
    disc = tier_discount(segment)
    return int(round(int(list_price or 0) * (1 - disc / 100.0)))


def part_available_qty(part_no: str) -> int:
    """Tồn KHẢ DỤNG toàn kho cho 1 part = Σ(qty_on_hand − qty_reserved)."""
    from apps.wms.models import InventoryItem
    agg = (InventoryItem.objects.filter(part_id=part_no)
           .aggregate(a=Sum(F('qty_on_hand') - F('qty_reserved'))))
    return int(agg['a'] or 0)
