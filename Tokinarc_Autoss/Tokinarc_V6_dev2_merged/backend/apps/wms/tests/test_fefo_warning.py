"""Cảnh báo quét nhầm lô FEFO khi pick."""
import datetime as dt

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User


@pytest.fixture
def kho():
    return User.objects.create(username='fw_kho', role=Role.WAREHOUSE)


@pytest.mark.django_db
def test_scan_pick_warns_on_wrong_lot(kho):
    from apps.catalog.models import Part
    from apps.wms.models import (Bin, InventoryItem, Lot, OutboundOrder, OutboundLine,
                                 Warehouse, Zone)
    part = Part.objects.create(tokin_part_no='FW-P', category='Tip', display_name_vi='Bép')
    w = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=w, code='MIG', name='MIG')
    b = Bin.objects.create(zone=z, rack='T1', bin_code='B01', full_code='HCM-MIG-T1-B01')
    InventoryItem.objects.create(bin=b, part=part, qty_on_hand=50)
    # Lô A hết hạn sớm (ưu tiên), Lô B hết hạn muộn
    Lot.objects.create(lot_no='LOT-A', part=part, qty_remaining=20,
                       received_date=dt.date(2026, 1, 1), expires_at=dt.date(2026, 7, 1), bin=b)
    Lot.objects.create(lot_no='LOT-B', part=part, qty_remaining=30,
                       received_date=dt.date(2026, 1, 1), expires_at=dt.date(2027, 1, 1), bin=b)
    ob = OutboundOrder.objects.create(code='OUT-FW', warehouse=w, status='picking',
                                      created_by=kho, updated_by=kho)
    OutboundLine.objects.create(outbound=ob, part=part, qty_ordered=5)
    c = APIClient(); c.force_authenticate(kho)

    # Quét lô B (muộn) → cảnh báo WRONG_LOT
    r = c.post(f'/api/v1/wms/outbound/{ob.id}/scan-pick/',
               {'code': 'FW-P', 'bin_code': 'HCM-MIG-T1-B01', 'qty': 5, 'lot_no': 'LOT-B'},
               format='json')
    assert r.status_code == 409 and r.data['code'] == 'WRONG_LOT'
    assert r.data['priority_lot'] == 'LOT-A'

    # Xác nhận lại (confirm_lot) → cho qua
    r2 = c.post(f'/api/v1/wms/outbound/{ob.id}/scan-pick/',
                {'code': 'FW-P', 'bin_code': 'HCM-MIG-T1-B01', 'qty': 5,
                 'lot_no': 'LOT-B', 'confirm_lot': True}, format='json')
    assert r2.status_code == 200 and r2.data['picked'] == 5
