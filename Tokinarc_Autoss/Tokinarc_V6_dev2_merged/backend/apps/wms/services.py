"""
Tokinarc V6.C — apps/wms/services.py

Logic nghiệp vụ kho tách khỏi viewset để test + tái dùng (tool bot cũng gọi).
Mọi thay đổi tồn đi qua đây để đảm bảo: ghi StockMovement + concurrency-safe.

Quy tắc concurrency:
  - adjust/receive/pick dùng select_for_update() trên InventoryItem.
  - Cập nhật qty bằng F() expression tránh race read-modify-write.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import F

from .models import (
    Bin, InventoryItem, MovementReason, OutboundLine, OutboundOrder,
    OutboundRule, PickListItem, SerialNumber, StockMovement, Lot,
)


class InsufficientStock(Exception):
    pass


def _wh_of_bin(bin_obj: Bin):
    return bin_obj.zone.warehouse


@transaction.atomic
def adjust_stock(*, bin_obj: Bin, part=None, torch=None, new_qty: int,
                 reason: str, user=None, note: str = '') -> InventoryItem:
    """Set tồn về new_qty tuyệt đối; ghi movement delta = new - old."""
    if (part is None) == (torch is None):
        raise ValueError("Phải có đúng một trong part/torch.")
    item, _ = InventoryItem.objects.select_for_update().get_or_create(
        bin=bin_obj, part=part, torch=torch,
        defaults={'qty_on_hand': 0},
    )
    delta = new_qty - item.qty_on_hand
    item.qty_on_hand = new_qty
    item.save(update_fields=['qty_on_hand', 'updated_at'])
    StockMovement.objects.create(
        warehouse=_wh_of_bin(bin_obj), part=part, torch=torch, bin=bin_obj,
        delta=delta, reason=reason or MovementReason.ADJUST,
        ref_kind='adjust', by_user=user, note=note,
    )
    return item


@transaction.atomic
def receive_stock(*, bin_obj: Bin, part=None, torch=None, qty: int,
                  user=None, ref_id: str = '', lot_no: str = '', lot_expires=None,
                  reason: str = MovementReason.INBOUND, ref_kind: str = 'inbound') -> InventoryItem:
    """+qty vào bin, ghi movement (inbound mặc định / return khi trả hàng), FIFO + Lot."""
    from datetime import date

    from django.utils import timezone

    if qty <= 0:
        raise ValueError("qty nhập phải > 0.")
    item, _ = InventoryItem.objects.select_for_update().get_or_create(
        bin=bin_obj, part=part, torch=torch, defaults={'qty_on_hand': 0},
    )
    # FIFO: ghi mốc nhập lần đầu (khi ô đang trống) để xếp xuất theo thời gian.
    fields = {'qty_on_hand': F('qty_on_hand') + qty}
    if item.qty_on_hand == 0 or item.received_at is None:
        fields['received_at'] = timezone.now()
    InventoryItem.objects.filter(pk=item.pk).update(**fields)
    StockMovement.objects.create(
        warehouse=_wh_of_bin(bin_obj), part=part, torch=torch, bin=bin_obj,
        delta=qty, reason=reason, ref_kind=ref_kind,
        ref_id=ref_id, by_user=user, note=(f'lot {lot_no}' if lot_no else ''),
    )
    # Lot tracking: tạo/cộng lô (chỉ cho part có lô).
    if lot_no and part is not None:
        lot, created = Lot.objects.select_for_update().get_or_create(
            lot_no=lot_no, defaults={'part': part, 'qty_remaining': 0,
                                     'received_date': date.today(), 'expires_at': lot_expires,
                                     'bin': bin_obj})
        Lot.objects.filter(pk=lot.pk).update(qty_remaining=F('qty_remaining') + qty)
        if not created and lot_expires and lot.expires_at != lot_expires:
            Lot.objects.filter(pk=lot.pk).update(expires_at=lot_expires)
    item.refresh_from_db()
    return item


@transaction.atomic
def issue_stock(*, bin_obj: Bin, part=None, torch=None, qty: int,
                user=None, ref_id: str = '') -> InventoryItem:
    """Xuất kho: -qty khỏi bin (kiểm tra tồn khả dụng), movement reason=outbound."""
    if qty <= 0:
        raise ValueError("qty xuất phải > 0.")
    item = (InventoryItem.objects.select_for_update()
            .filter(bin=bin_obj, part=part, torch=torch).first())
    if item is None or item.available_qty < qty:
        have = item.available_qty if item else 0
        raise InsufficientStock(f"Tồn khả dụng {have} < {qty}.")
    InventoryItem.objects.filter(pk=item.pk).update(qty_on_hand=F('qty_on_hand') - qty)
    StockMovement.objects.create(
        warehouse=_wh_of_bin(bin_obj), part=part, torch=torch, bin=bin_obj,
        delta=-qty, reason=MovementReason.OUTBOUND, ref_kind='outbound',
        ref_id=ref_id, by_user=user,
    )
    item.refresh_from_db()
    return item


@transaction.atomic
def transfer_stock(*, from_bin: Bin, to_bin: Bin, part=None, torch=None,
                   qty: int, user=None) -> None:
    """Chuyển nội bộ / liên kho: -qty bin nguồn, +qty bin đích, 2 movement."""
    if qty <= 0:
        raise ValueError("qty chuyển phải > 0.")
    src = InventoryItem.objects.select_for_update().get(bin=from_bin, part=part, torch=torch)
    if src.available_qty < qty:
        raise InsufficientStock(f"Tồn khả dụng {src.available_qty} < {qty}.")
    InventoryItem.objects.filter(pk=src.pk).update(qty_on_hand=F('qty_on_hand') - qty)
    dst, _ = InventoryItem.objects.select_for_update().get_or_create(
        bin=to_bin, part=part, torch=torch, defaults={'qty_on_hand': 0})
    InventoryItem.objects.filter(pk=dst.pk).update(qty_on_hand=F('qty_on_hand') + qty)
    StockMovement.objects.create(warehouse=_wh_of_bin(from_bin), part=part, torch=torch,
                                 bin=from_bin, delta=-qty, reason=MovementReason.TRANSFER,
                                 ref_kind='transfer', by_user=user)
    StockMovement.objects.create(warehouse=_wh_of_bin(to_bin), part=part, torch=torch,
                                 bin=to_bin, delta=qty, reason=MovementReason.TRANSFER,
                                 ref_kind='transfer', by_user=user)


@transaction.atomic
def generate_pick_list(outbound: OutboundOrder) -> list[PickListItem]:
    """
    Sinh pick list theo rule (FIFO/FEFO/NEAREST). Phân bin cho từng dòng,
    giữ tồn (qty_reserved) để tránh phân trùng.
    """
    picks: list[PickListItem] = []
    for line in outbound.lines.select_related('part', 'torch'):
        remaining = line.qty_ordered - line.qty_picked
        if remaining <= 0:
            continue
        candidates = _candidate_inventory(outbound, line)
        for item in candidates:
            if remaining <= 0:
                break
            take = min(remaining, item.available_qty)
            if take <= 0:
                continue
            lot = None
            if line.part_id and outbound.rule == OutboundRule.FEFO:
                lot = (Lot.objects.filter(part=line.part, bin=item.bin, qty_remaining__gt=0)
                       .order_by('expires_at').first())
            pick = PickListItem.objects.create(
                outbound_line=line, bin=item.bin, lot=lot, qty=take)
            picks.append(pick)
            # giữ tồn
            InventoryItem.objects.filter(pk=item.pk).update(
                qty_reserved=F('qty_reserved') + take)
            remaining -= take
        if remaining > 0:
            raise InsufficientStock(
                f"Không đủ tồn cho {line.part_id or line.torch_id}: thiếu {remaining}.")
    outbound.status = 'picking'
    outbound.save(update_fields=['status'])
    return picks


def _candidate_inventory(outbound: OutboundOrder, line: OutboundLine):
    """Trả InventoryItem ứng viên theo rule, chỉ trong warehouse của outbound."""
    qs = (InventoryItem.objects.select_for_update()
          .filter(bin__zone__warehouse=outbound.warehouse,
                  part=line.part, torch=line.torch, qty_on_hand__gt=F('qty_reserved')))
    if outbound.rule == OutboundRule.FEFO and line.part_id:
        # ưu tiên bin có lot hết hạn sớm nhất
        return qs.order_by('bin__lot__expires_at')
    if outbound.rule == OutboundRule.NEAREST:
        return qs.order_by('bin__full_code')   # giả định full_code phản ánh khoảng cách cửa
    # FIFO: ưu tiên ô có hàng nhập SỚM NHẤT (theo received_at); nulls cuối.
    return qs.order_by(F('received_at').asc(nulls_last=True), 'bin__full_code')


@transaction.atomic
def confirm_pick_and_ship(outbound: OutboundOrder, user=None) -> None:
    """Xác nhận đã soạn + giao: trừ tồn thực, nhả reserved, ghi movement, update serial."""
    for line in outbound.lines.all():
        for pick in line.picks.filter(is_picked=False):
            item = InventoryItem.objects.select_for_update().get(
                bin=pick.bin, part=line.part, torch=line.torch)
            InventoryItem.objects.filter(pk=item.pk).update(
                qty_on_hand=F('qty_on_hand') - pick.qty,
                qty_reserved=F('qty_reserved') - pick.qty)
            StockMovement.objects.create(
                warehouse=outbound.warehouse, part=line.part, torch=line.torch,
                bin=pick.bin, delta=-pick.qty, reason=MovementReason.OUTBOUND,
                ref_kind='outbound', ref_id=outbound.code, by_user=user)
            # Lot tracking: trừ tồn của lô đã pick (FEFO).
            if pick.lot_id:
                Lot.objects.filter(pk=pick.lot_id).update(
                    qty_remaining=F('qty_remaining') - pick.qty)
            pick.is_picked = True
            pick.save(update_fields=['is_picked'])
            if pick.serial_id:
                SerialNumber.objects.filter(pk=pick.serial_id).update(
                    status='shipped', sold_to_customer=outbound.customer,
                    sold_order=outbound.sales_order_code)
        line.qty_picked = line.qty_ordered
        line.save(update_fields=['qty_picked'])
    from django.utils import timezone
    outbound.status = 'shipped'
    outbound.shipped_at = timezone.now()
    outbound.save(update_fields=['status', 'shipped_at'])
    _sync_sales_order_completed(outbound, user)


def _sync_sales_order_completed(outbound, user=None) -> None:
    """Sync ngược kho→CRM: giao xong → đơn bán `completed` + báo 🔔 cho sale."""
    if not outbound.sales_order_code:
        return
    try:
        from apps.common.models import notify
        from apps.sales.models import SalesOrder
    except Exception:  # noqa: BLE001
        return
    order = (SalesOrder.objects.filter(code=outbound.sales_order_code)
             .exclude(status__in=['completed', 'cancelled']).first())
    if order is None:
        return
    order.status = 'completed'
    order.save(update_fields=['status'])
    if order.owner_id:
        notify(order.owner, 'order_shipped',
               f'Đơn {order.code} đã giao xong (phiếu xuất {outbound.code}).',
               link='/orders')
