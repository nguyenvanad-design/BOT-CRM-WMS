"""Kho từ chối phiếu xuất → đơn về active + notify sale, nhả reserved."""
import datetime as dt

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.common.models import Notification
from apps.crm.models import Customer
from apps.sales.models import SalesOrder


@pytest.mark.django_db
def test_reject_outbound_reverts_order_and_notifies():
    from apps.catalog.models import Part
    from apps.wms.models import (Bin, InventoryItem, OutboundOrder, OutboundLine,
                                 PickListItem, Warehouse, Zone)
    sale = User.objects.create(username='or_sale', role=Role.SALES)
    kho = User.objects.create(username='or_kho', role=Role.WAREHOUSE)
    cust = Customer.objects.create(code='KH-OR', name='ACME', owner=sale,
                                   created_by=sale, updated_by=sale)
    part = Part.objects.create(tokin_part_no='OR-P', category='Tip', display_name_vi='Bép')
    w = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=w, code='MIG', name='MIG')
    b = Bin.objects.create(zone=z, rack='T1', bin_code='B01', full_code='HCM-MIG-T1-B01')
    InventoryItem.objects.create(bin=b, part=part, qty_on_hand=10, qty_reserved=5)
    order = SalesOrder.objects.create(code='HD-OR-1', customer=cust,
                                      issued_date=dt.date(2026, 6, 1), total_vnd=100,
                                      status='shipping', owner=sale)
    ob = OutboundOrder.objects.create(code='OUT-OR-1', warehouse=w, customer=cust,
                                      sales_order_code='HD-OR-1', status='picking',
                                      created_by=kho, updated_by=kho)
    ol = OutboundLine.objects.create(outbound=ob, part=part, qty_ordered=5)
    PickListItem.objects.create(outbound_line=ol, bin=b, qty=5, is_picked=False)

    c = APIClient(); c.force_authenticate(kho)
    r = c.post(f'/api/v1/wms/outbound/{ob.id}/reject/', {'reason': 'hết hàng'}, format='json')
    assert r.status_code == 200 and r.data['status'] == 'cancelled'
    order.refresh_from_db(); assert order.status == 'active'
    assert InventoryItem.objects.get(bin=b, part=part).qty_reserved == 0
    assert Notification.objects.filter(user=sale, kind='outbound_rejected').exists()
