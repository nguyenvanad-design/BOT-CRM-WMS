"""
Tokinarc — apps/catalog/costing.py

Giá vốn bình quân gia quyền (WAC — Weighted Average Cost).
Gọi SAU khi đã cộng tồn (receive_stock) với giá mua thực của lô vừa nhập.

  new_cost = (tồn_cũ × vốn_cũ + SL_nhận × giá_mua) / (tồn_cũ + SL_nhận)

Idempotent KHÔNG đảm bảo (vì phụ thuộc tồn hiện tại) → chỉ gọi 1 lần mỗi lần nhận.
"""
from __future__ import annotations


def update_wac(part, recv_qty, unit_cost) -> None:
    """Cập nhật part.cost_vnd theo WAC. recv_qty/unit_cost của lô vừa nhập."""
    if part is None or not recv_qty or recv_qty <= 0:
        return
    from django.db.models import Sum

    from apps.wms.models import InventoryItem

    # Tồn hiện tại ĐÃ gồm phần vừa nhận (hàm gọi sau receive_stock) → trừ ra.
    on_hand = InventoryItem.objects.filter(part=part).aggregate(s=Sum('qty_on_hand'))['s'] or 0
    prev_qty = max(0, int(on_hand) - int(recv_qty))
    old_cost = float(part.cost_vnd or 0)
    denom = prev_qty + int(recv_qty)
    if denom <= 0:
        return
    new_cost = (prev_qty * old_cost + int(recv_qty) * float(unit_cost or 0)) / denom
    part.cost_vnd = int(round(new_cost))
    part.save(update_fields=['cost_vnd'])
