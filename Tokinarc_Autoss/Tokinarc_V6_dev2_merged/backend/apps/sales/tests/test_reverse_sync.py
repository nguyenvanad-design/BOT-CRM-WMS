"""Sync ngược kho→đơn: outbound shipped → SalesOrder completed + notify."""
import datetime as dt

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.common.models import Notification
from apps.crm.models import Customer
from apps.sales.models import SalesOrder, SalesOrderLine


@pytest.mark.django_db
def test_ship_completes_order_and_notifies():
    from apps.catalog.models import Part
    from apps.wms.models import (Bin, InventoryItem, OutboundOrder, OutboundLine,
                                 PickListItem, Warehouse, Zone)
    from apps.wms import services
    sale = User.objects.create(username='rs_sale', role=Role.SALES)
    kho = User.objects.create(username='rs_kho', role=Role.WAREHOUSE)
    cust = Customer.objects.create(code='KH-RS', name='ACME', owner=sale,
                                   created_by=sale, updated_by=sale)
    part = Part.objects.create(tokin_part_no='RS-P', category='Tip', display_name_vi='Bép')
    w = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=w, code='MIG', name='MIG')
    b = Bin.objects.create(zone=z, rack='T1', bin_code='B01', full_code='HCM-MIG-T1-B01')
    InventoryItem.objects.create(bin=b, part=part, qty_on_hand=10, qty_reserved=5)
    order = SalesOrder.objects.create(code='HD-RS-1', customer=cust,
                                      issued_date=dt.date(2026, 6, 1), total_vnd=100,
                                      status='shipping', owner=sale)
    SalesOrderLine.objects.create(order=order, part=part, description='x', qty=5,
                                  unit_price=20, line_total=100)
    ob = OutboundOrder.objects.create(code='OUT-RS-1', warehouse=w, customer=cust,
                                      sales_order_code='HD-RS-1',
                                      created_by=kho, updated_by=kho)
    ol = OutboundLine.objects.create(outbound=ob, part=part, qty_ordered=5)
    PickListItem.objects.create(outbound_line=ol, bin=b, qty=5, is_picked=False)

    services.confirm_pick_and_ship(ob, user=kho)
    order.refresh_from_db()
    assert order.status == 'completed'
    assert Notification.objects.filter(user=sale, kind='order_shipped').exists()
