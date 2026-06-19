"""
Tokinarc V6.C — apps/sales/services.py

Logic tính tiền + thanh toán tách khỏi viewset.
line_total và total_vnd luôn do BE tính (không nhận từ FE) — chống sai lệch.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction


def compute_line_total(qty: int, unit_price, discount_pct) -> Decimal:
    gross = Decimal(qty) * Decimal(unit_price)
    disc = gross * Decimal(discount_pct) / Decimal(100)
    return (gross - disc).quantize(Decimal('1'))


@transaction.atomic
def recompute_order_total(order) -> None:
    total = sum((line.line_total for line in order.lines.all()), Decimal(0))
    order.total_vnd = total
    order.save(update_fields=['total_vnd'])


@transaction.atomic
def record_payment(order, *, amount, paid_at, method, reference='', user=None):
    from .models import Payment
    if amount <= 0:
        raise ValueError("Số tiền thanh toán phải > 0.")
    if order.paid_vnd + Decimal(amount) > order.total_vnd:
        raise ValueError("Tổng thanh toán vượt quá giá trị đơn.")
    p = Payment.objects.create(order=order, amount_vnd=amount, paid_at=paid_at,
                               method=method, reference=reference,
                               created_by=user, updated_by=user)
    order.paid_vnd = order.paid_vnd + Decimal(amount)
    if order.paid_vnd >= order.total_vnd and order.status == 'shipping':
        order.status = 'completed'
    order.save(update_fields=['paid_vnd', 'status'])

    # Publish sau commit (publisher dùng transaction.on_commit) → handler
    # on_payment_received recompute paid_vnd từ Sum(payments) một cách idempotent.
    from tokinarc.eventbus.channels import Channel
    from tokinarc.eventbus.publisher import publish
    publish(Channel.PAYMENT_RECEIVED, {
        'order_id': str(order.id),
        'amount_vnd': str(amount),
        'method': method,
    })
    return p
