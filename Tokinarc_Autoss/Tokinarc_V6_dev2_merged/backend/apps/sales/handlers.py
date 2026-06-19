"""
Tokinarc V6 — apps/sales/handlers.py

Handler async cho domain sales. Auto-import qua SalesConfig.ready() →
@subscribe decorator chạy ở import time → register vào listener registry.

Quy tắc (xem docs/dev/EVENTS_HANDLERS.md §6): handler PHẢI idempotent — có thể
chạy nhiều lần với cùng payload (worker restart, dead-letter retry, HA 2 worker).
Pattern dùng ở đây: recompute từ source thay vì cộng dồn.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from tokinarc.eventbus.channels import Channel
from tokinarc.eventbus.listener import subscribe

logger = logging.getLogger(__name__)


@subscribe(Channel.PAYMENT_RECEIVED)
def on_payment_received(payload: dict) -> None:
    """
    Khi có payment mới → cập nhật SalesOrder.paid_vnd từ tổng payments.
    Nếu đã thu đủ (paid_vnd >= total_vnd) và đơn đang shipping → COMPLETED.

    Idempotent: tính lại paid_vnd = Sum(payments.amount_vnd), KHÔNG cộng dồn,
    nên gọi lại nhiều lần vẫn ra cùng kết quả.
    """
    from django.db import transaction
    from django.db.models import Sum

    from apps.sales.models import OrderStatus, SalesOrder

    order_id = payload.get("order_id")
    if not order_id:
        logger.warning("payment_received_missing_order_id", extra={"payload": payload})
        return

    with transaction.atomic():
        try:
            order = SalesOrder.objects.select_for_update().get(id=order_id)
        except SalesOrder.DoesNotExist:
            logger.warning("payment_received_order_not_found", extra={"order_id": order_id})
            return

        total_paid = order.payments.aggregate(s=Sum("amount_vnd"))["s"] or Decimal(0)
        order.paid_vnd = total_paid

        if order.paid_vnd >= order.total_vnd and order.status not in (
            OrderStatus.COMPLETED,
            OrderStatus.CANCELLED,
        ):
            order.status = OrderStatus.COMPLETED

        order.save(update_fields=["paid_vnd", "status", "updated_at"])

    logger.info(
        "payment_processed",
        extra={"order_code": order.code, "paid_vnd": str(order.paid_vnd),
               "status": order.status},
    )


@subscribe(Channel.ORDER_SHIPPED)
def on_order_shipped(payload: dict) -> None:
    """
    Đơn chuyển sang trạng thái giao → log (mở rộng: bắn notification cho kho,
    tạo OutboundOrder, gửi Zalo cho khách...). Hiện chỉ log để xác nhận pipeline
    event chạy end-to-end.

    Idempotent tự nhiên: chỉ đọc + log, không ghi DB.
    """
    logger.info("order_shipped_handled", extra={
        "order": payload.get("order"),
        "customer_id": payload.get("customer_id"),
    })
