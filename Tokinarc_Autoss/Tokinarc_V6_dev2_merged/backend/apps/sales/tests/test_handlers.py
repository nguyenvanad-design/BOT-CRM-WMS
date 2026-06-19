"""
Tokinarc V6 — apps/sales/tests/test_handlers.py

Test handler async (gọi function trực tiếp, bypass LISTEN/NOTIFY — SQLite không
hỗ trợ). Trọng tâm: handler đúng + IDEMPOTENT (gọi nhiều lần ra cùng kết quả).
"""
from __future__ import annotations

import datetime as dt
import itertools
from decimal import Decimal

import factory
import pytest

from apps.accounts.models import Role, User
from apps.crm.models import Customer
from apps.sales.handlers import on_order_shipped, on_payment_received
from apps.sales.models import OrderStatus, Payment, SalesOrder


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
    username = factory.Sequence(lambda n: f'sale{n}')
    role = Role.SALES


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer
    code = factory.Sequence(lambda n: f'KH-{n:04d}')
    name = factory.Faker('company', locale='vi_VN')
    segment = 'factory'
    owner = factory.SubFactory(UserFactory)


_code_seq = itertools.count(1)


def _order(sale, total, status=OrderStatus.SHIPPING):
    cust = CustomerFactory(owner=sale)
    return SalesOrder.objects.create(
        code=f'HD-{next(_code_seq):04d}',
        customer=cust, issued_date=dt.date(2026, 6, 1),
        total_vnd=Decimal(total), paid_vnd=Decimal(0),
        status=status, owner=sale,
    )


@pytest.mark.django_db
def test_payment_handler_completes_order_when_fully_paid():
    sale = UserFactory()
    order = _order(sale, total=1_000_000)
    Payment.objects.create(order=order, amount_vnd=Decimal('1000000'),
                           paid_at=dt.date(2026, 6, 17), method='transfer',
                           created_by=sale, updated_by=sale)

    on_payment_received({'order_id': str(order.id)})

    order.refresh_from_db()
    assert order.paid_vnd == Decimal('1000000')
    assert order.status == OrderStatus.COMPLETED


@pytest.mark.django_db
def test_payment_handler_idempotent():
    """Gọi handler 2 lần → paid_vnd tính lại từ Sum, không double count."""
    sale = UserFactory()
    order = _order(sale, total=1_000_000)
    Payment.objects.create(order=order, amount_vnd=Decimal('1000000'),
                           paid_at=dt.date(2026, 6, 17), method='transfer',
                           created_by=sale, updated_by=sale)

    on_payment_received({'order_id': str(order.id)})
    on_payment_received({'order_id': str(order.id)})  # gọi lại

    order.refresh_from_db()
    assert order.paid_vnd == Decimal('1000000')   # KHÔNG phải 2_000_000


@pytest.mark.django_db
def test_payment_handler_partial_keeps_status():
    sale = UserFactory()
    order = _order(sale, total=1_000_000)
    Payment.objects.create(order=order, amount_vnd=Decimal('400000'),
                           paid_at=dt.date(2026, 6, 17), method='cash',
                           created_by=sale, updated_by=sale)

    on_payment_received({'order_id': str(order.id)})

    order.refresh_from_db()
    assert order.paid_vnd == Decimal('400000')
    assert order.status == OrderStatus.SHIPPING   # chưa đủ → giữ nguyên


@pytest.mark.django_db
def test_payment_handler_missing_order_id_no_crash():
    on_payment_received({})            # thiếu order_id → log + return, không raise


@pytest.mark.django_db
def test_payment_handler_unknown_order_no_crash():
    on_payment_received({'order_id': '00000000-0000-0000-0000-000000000000'})


@pytest.mark.django_db
def test_order_shipped_handler_no_crash():
    on_order_shipped({'order': 'HD-9999', 'customer_id': 'x'})
