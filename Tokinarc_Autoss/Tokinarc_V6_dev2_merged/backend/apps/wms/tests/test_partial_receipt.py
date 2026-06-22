"""Nhận một phần theo ASN: giao thiếu → partial (mở), nhận tiếp → putaway."""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User


@pytest.fixture
def kho():
    return User.objects.create(username='pr_kho', role=Role.WAREHOUSE)


@pytest.mark.django_db
def test_partial_receipt_two_rounds(kho):
    from apps.catalog.models import Part
    from apps.wms.models import (Bin, InboundLine, InboundOrder, InventoryItem,
                                 Warehouse, Zone)
    part = Part.objects.create(tokin_part_no='PR-P', category='Tip', display_name_vi='Bép')
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='A', name='A')
    b = Bin.objects.create(zone=z, rack='R01', bin_code='B1', full_code='HCM-A-R01-B1')
    io = InboundOrder.objects.create(code='IN-PR', warehouse=wh, created_by=kho, updated_by=kho)
    line = InboundLine.objects.create(inbound=io, part=part, qty_expected=100, target_bin=b)
    c = APIClient(); c.force_authenticate(kho)

    # Đợt 1: NCC giao 80/100
    c.post(f'/api/v1/wms/inbound/{io.id}/scan-receive/', {'code': 'PR-P', 'qty': 80}, format='json')
    r1 = c.post(f'/api/v1/wms/inbound/{io.id}/confirm/', {'partial': True}, format='json')
    assert r1.data['status'] == 'partial'
    assert InventoryItem.objects.get(bin=b, part=part).qty_on_hand == 80
    line.refresh_from_db(); assert line.qty_putaway == 80

    # Đợt 2: giao nốt 20 → đủ → putaway, tồn = 100 (không double-count)
    c.post(f'/api/v1/wms/inbound/{io.id}/scan-receive/', {'code': 'PR-P', 'qty': 20}, format='json')
    r2 = c.post(f'/api/v1/wms/inbound/{io.id}/confirm/')
    assert r2.data['status'] == 'putaway'
    assert InventoryItem.objects.get(bin=b, part=part).qty_on_hand == 100
