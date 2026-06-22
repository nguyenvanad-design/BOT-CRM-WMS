"""
Tokinarc V6.C — apps/sales/tests/test_sales.py
"""
from __future__ import annotations

import datetime as dt

import factory
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.models import Customer
from apps.sales import services
from apps.sales.models import SalesOrder


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


@pytest.fixture
def sale(db):
    return UserFactory(role=Role.SALES)


@pytest.fixture
def auth(sale):
    c = APIClient(); c.force_authenticate(sale)
    return c


@pytest.mark.django_db
def test_line_total_computed_by_backend(auth, sale):
    cust = CustomerFactory(owner=sale)
    r = auth.post('/api/v1/sales/orders/', {
        'code': 'HD-0001', 'customer': str(cust.id), 'issued_date': '2026-06-01',
        'payment_terms': 'net_30',
        'lines': [{'description': 'Béc hàn', 'qty': 10, 'unit_price': 45000, 'discount_pct': 10}],
    }, format='json')
    assert r.status_code == 201
    # 10*45000 = 450000, -10% = 405000
    assert r.data['lines'][0]['line_total'] == '405000'
    assert r.data['total_vnd'] == '405000'


@pytest.mark.django_db
def test_sign_ship_flow(auth, sale):
    cust = CustomerFactory(owner=sale)
    r = auth.post('/api/v1/sales/orders/', {
        'code': 'HD-0002', 'customer': str(cust.id), 'issued_date': '2026-06-01',
        'lines': [{'description': 'X', 'qty': 1, 'unit_price': 1000000}],
    }, format='json')
    oid = r.data['id']
    assert auth.post(f'/api/v1/sales/orders/{oid}/ship/').status_code == 409  # chưa active
    assert auth.post(f'/api/v1/sales/orders/{oid}/sign/').status_code == 200
    assert auth.post(f'/api/v1/sales/orders/{oid}/ship/').status_code == 200


@pytest.mark.django_db
def test_payment_reduces_debt(sale):
    cust = CustomerFactory(owner=sale)
    order = SalesOrder.objects.create(code='HD-0003', customer=cust, issued_date=dt.date(2026, 6, 1),
                                      total_vnd=1000000, owner=sale)
    services.record_payment(order, amount=600000, paid_at=dt.date(2026, 6, 2),
                            method='transfer', user=sale)
    order.refresh_from_db()
    assert order.paid_vnd == 600000
    assert order.debt_amount == 400000


@pytest.mark.django_db
def test_payment_cannot_exceed_total(sale):
    cust = CustomerFactory(owner=sale)
    order = SalesOrder.objects.create(code='HD-0004', customer=cust, issued_date=dt.date(2026, 6, 1),
                                      total_vnd=500000, owner=sale)
    with pytest.raises(ValueError):
        services.record_payment(order, amount=600000, paid_at=dt.date(2026, 6, 2),
                                method='cash', user=sale)


@pytest.mark.django_db
def test_customer_role_blocked(db):
    cu = User.objects.create(username='kh1', role=Role.CUSTOMER)
    c = APIClient(); c.force_authenticate(cu)
    assert c.get('/api/v1/sales/orders/').status_code == 403


@pytest.mark.django_db
def test_create_invoice_with_vat(db):
    from apps.accounts.models import Role as R, User as U
    from apps.sales.models import Invoice
    mgr = U.objects.create(username='mg', role=R.MANAGER)
    cust = CustomerFactory()
    order = SalesOrder.objects.create(code='HD-INV-1', customer=cust, issued_date=dt.date(2026, 6, 1),
                                      total_vnd=10_000_000, status='active', owner=mgr)
    c = APIClient(); c.force_authenticate(mgr)
    r = c.post(f'/api/v1/sales/orders/{order.id}/create-invoice/', {'tax_pct': 8}, format='json')
    assert r.status_code == 201
    assert int(r.data['tax_vnd']) == 800_000 and int(r.data['total_vnd']) == 10_800_000
    assert Invoice.objects.filter(order=order).exists()


@pytest.mark.django_db
def test_ceo_can_access_sales_and_wms(db):
    """CEO phải đọc được đơn bán + WMS (regression: role-set từng sót ceo)."""
    ceo = User.objects.create(username='ceo1', role=Role.CEO)
    c = APIClient(); c.force_authenticate(ceo)
    assert c.get('/api/v1/sales/orders/').status_code == 200
    assert c.get('/api/v1/wms/inventory/').status_code == 200


# ─── N1.2 ship → tự sinh WMS Outbound ────────────────────────────────────
@pytest.mark.django_db
def test_ship_creates_wms_outbound(auth, sale):
    from apps.catalog.models import Part
    from apps.wms.models import OutboundOrder, Warehouse
    Warehouse.objects.create(code='HCM', name='Kho HCM', is_active=True, is_default=True)
    Part.objects.create(tokin_part_no='P-001', category='tip', display_name_vi='Béc')
    cust = CustomerFactory(owner=sale)
    r = auth.post('/api/v1/sales/orders/', {
        'code': 'HD-OB-1', 'customer': str(cust.id), 'issued_date': '2026-06-01',
        'lines': [{'description': 'Béc', 'part': 'P-001', 'qty': 5, 'unit_price': 10000}],
    }, format='json')
    oid = r.data['id']
    auth.post(f'/api/v1/sales/orders/{oid}/sign/')
    rs = auth.post(f'/api/v1/sales/orders/{oid}/ship/')
    assert rs.status_code == 200
    ob = OutboundOrder.objects.get(sales_order_code='HD-OB-1')
    assert ob.customer_id == cust.id and ob.lines.count() == 1
    assert rs.data['outbound_code'] == ob.code
