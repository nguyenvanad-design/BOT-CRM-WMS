"""Sửa đơn sau ký: đổi địa chỉ/SL khi chưa giao; chặn khi đã giao."""
import datetime as dt

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.models import Customer
from apps.sales.models import SalesOrder, SalesOrderLine


def _order(owner, status='active', shipped=0):
    from apps.catalog.models import Part
    cust = Customer.objects.create(code=f'KH-AM{status}', name='ACME', owner=owner,
                                   created_by=owner, updated_by=owner)
    part = Part.objects.create(tokin_part_no=f'AM-{status}', category='Tip', display_name_vi='B')
    o = SalesOrder.objects.create(code=f'HD-AM-{status}', customer=cust,
                                  issued_date=dt.date(2026, 6, 1), total_vnd=200,
                                  status=status, owner=owner)
    ln = SalesOrderLine.objects.create(order=o, part=part, description='Bép', qty=10,
                                       unit_price=20, line_total=200, shipped_qty=shipped)
    return o, ln


@pytest.mark.django_db
def test_amend_active_order_changes_qty_and_address():
    mgr = User.objects.create(username='am_mgr', role=Role.MANAGER)
    o, ln = _order(mgr)
    c = APIClient(); c.force_authenticate(mgr)
    r = c.post(f'/api/v1/sales/orders/{o.id}/amend/',
               {'ship_address': 'KCN Sóng Thần', 'lines': [{'id': str(ln.id), 'qty': 6}]},
               format='json')
    assert r.status_code == 200
    o.refresh_from_db(); ln.refresh_from_db()
    assert o.ship_address == 'KCN Sóng Thần'
    assert ln.qty == 6 and int(ln.line_total) == 120 and int(o.total_vnd) == 120


@pytest.mark.django_db
def test_amend_blocked_after_shipping():
    mgr = User.objects.create(username='am_mgr2', role=Role.MANAGER)
    o, ln = _order(mgr, status='shipping')
    c = APIClient(); c.force_authenticate(mgr)
    r = c.post(f'/api/v1/sales/orders/{o.id}/amend/', {'ship_address': 'X'}, format='json')
    assert r.status_code == 409


@pytest.mark.django_db
def test_amend_qty_below_shipped_rejected():
    mgr = User.objects.create(username='am_mgr3', role=Role.MANAGER)
    o, ln = _order(mgr, status='active', shipped=8)
    c = APIClient(); c.force_authenticate(mgr)
    r = c.post(f'/api/v1/sales/orders/{o.id}/amend/',
               {'lines': [{'id': str(ln.id), 'qty': 5}]}, format='json')
    assert r.status_code == 409
