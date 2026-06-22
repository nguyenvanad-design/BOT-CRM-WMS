"""Giao một phần + backorder: outbound pick thiếu → partial, đơn giữ shipping."""
import datetime as dt

import pytest

from apps.accounts.models import Role, User
from apps.crm.models import Customer
from apps.sales.models import SalesOrder, SalesOrderLine


def _setup():
    from apps.catalog.models import Part
    from apps.wms.models import Bin, InventoryItem, Warehouse, Zone
    sale = User.objects.create(username='pf_sale', role=Role.SALES)
    kho = User.objects.create(username='pf_kho', role=Role.WAREHOUSE)
    cust = Customer.objects.create(code='KH-PF', name='ACME', owner=sale,
                                   created_by=sale, updated_by=sale)
    part = Part.objects.create(tokin_part_no='PF-P', category='Tip', display_name_vi='Bép')
    w = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=w, code='MIG', name='MIG')
    b = Bin.objects.create(zone=z, rack='T1', bin_code='B01', full_code='HCM-MIG-T1-B01')
    InventoryItem.objects.create(bin=b, part=part, qty_on_hand=100, qty_reserved=60)
    return sale, kho, cust, part, w, b


@pytest.mark.django_db
def test_partial_ship_keeps_order_shipping_and_backorder():
    from apps.wms.models import OutboundOrder, OutboundLine, PickListItem
    from apps.wms import services
    sale, kho, cust, part, w, b = _setup()
    order = SalesOrder.objects.create(code='HD-PF-1', customer=cust,
                                      issued_date=dt.date(2026, 6, 1), total_vnd=100,
                                      status='shipping', owner=sale)
    SalesOrderLine.objects.create(order=order, part=part, description='x', qty=100,
                                  unit_price=1, line_total=100)
    ob = OutboundOrder.objects.create(code='OUT-PF-1', warehouse=w, customer=cust,
                                      sales_order_code='HD-PF-1', created_by=kho, updated_by=kho)
    ol = OutboundLine.objects.create(outbound=ob, part=part, qty_ordered=100)
    # Chỉ pick 60/100
    PickListItem.objects.create(outbound_line=ol, bin=b, qty=60, is_picked=False)
    services.confirm_pick_and_ship(ob, user=kho)

    ob.refresh_from_db(); ol.refresh_from_db(); order.refresh_from_db()
    assert ob.status == 'partial'
    assert ol.qty_picked == 60
    assert order.status == 'shipping'   # chưa completed vì còn backorder
    sol = order.lines.get(part=part)
    assert sol.shipped_qty == 60        # backorder = 40
