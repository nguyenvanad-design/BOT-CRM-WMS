"""Xuất kho bằng QUÉT thuần (scan-pick, không pick-list): ship phải chốt được,
KHÔNG trừ tồn lần 2. Phiếu đã sinh pick-list thì chặn quét tay (tránh trừ đôi)."""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User


@pytest.fixture
def kho():
    return User.objects.create(username='ss_kho', role=Role.WAREHOUSE)


@pytest.fixture
def stock(kho):
    from apps.catalog.models import Part
    from apps.wms.models import Bin, InventoryItem, Warehouse, Zone
    part = Part.objects.create(tokin_part_no='SS-P', category='Tip', display_name_vi='Bép')
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='A', name='A')
    b = Bin.objects.create(zone=z, rack='R01', bin_code='B1', full_code='HCM-A-R01-B1')
    inv = InventoryItem.objects.create(bin=b, part=part, qty_on_hand=20)
    return part, wh, b, inv


def _outbound(kho, wh, part, qty, code):
    from apps.wms.models import OutboundLine, OutboundOrder
    ob = OutboundOrder.objects.create(code=code, warehouse=wh, created_by=kho, updated_by=kho)
    OutboundLine.objects.create(outbound=ob, part=part, qty_ordered=qty)
    return ob


@pytest.mark.django_db
def test_scan_pick_then_ship_no_double_deduct(kho, stock):
    """Quét đủ → Giao hàng: 200 shipped, tồn chỉ trừ 1 lần (lúc quét)."""
    from apps.wms.models import InventoryItem
    part, wh, b, inv = stock
    ob = _outbound(kho, wh, part, 5, 'OUT-SS1')
    c = APIClient(); c.force_authenticate(kho)

    r = c.post(f'/api/v1/wms/outbound/{ob.id}/scan-pick/',
               {'code': 'SS-P', 'bin_code': b.full_code, 'qty': 5}, format='json')
    assert r.status_code == 200 and r.data['all_done'] is True
    assert InventoryItem.objects.get(pk=inv.pk).qty_on_hand == 15   # trừ NGAY khi quét

    r = c.post(f'/api/v1/wms/outbound/{ob.id}/ship/')
    assert r.status_code == 200, r.data          # bug cũ: 400 "Chưa soạn..."
    assert r.data['status'] == 'shipped'
    assert InventoryItem.objects.get(pk=inv.pk).qty_on_hand == 15   # KHÔNG trừ lần 2


@pytest.mark.django_db
def test_scan_pick_partial_then_ship_partial(kho, stock):
    """Quét thiếu (3/8) → Giao = giao MỘT PHẦN (partial), không lỗi."""
    part, wh, b, inv = stock
    ob = _outbound(kho, wh, part, 8, 'OUT-SS2')
    c = APIClient(); c.force_authenticate(kho)
    c.post(f'/api/v1/wms/outbound/{ob.id}/scan-pick/',
           {'code': 'SS-P', 'bin_code': b.full_code, 'qty': 3}, format='json')
    r = c.post(f'/api/v1/wms/outbound/{ob.id}/ship/')
    assert r.status_code == 200 and r.data['status'] == 'partial'


@pytest.mark.django_db
def test_ship_with_nothing_picked_still_blocked(kho, stock):
    """Chưa soạn gì (không pick, không quét) → ship vẫn bị chặn 400."""
    part, wh, b, inv = stock
    ob = _outbound(kho, wh, part, 5, 'OUT-SS3')
    ob.status = 'picking'; ob.save(update_fields=['status'])
    c = APIClient(); c.force_authenticate(kho)
    r = c.post(f'/api/v1/wms/outbound/{ob.id}/ship/')
    assert r.status_code == 400


@pytest.mark.django_db
def test_scan_pick_blocked_when_picklist_exists(kho, stock):
    """Đã sinh pick-list (giữ tồn) → quét tay bị chặn 409 (tránh trừ tồn 2 lần)."""
    from apps.wms.models import InventoryItem
    part, wh, b, inv = stock
    ob = _outbound(kho, wh, part, 4, 'OUT-SS4')
    c = APIClient(); c.force_authenticate(kho)
    assert c.get(f'/api/v1/wms/outbound/{ob.id}/pick-list/').status_code == 200
    r = c.post(f'/api/v1/wms/outbound/{ob.id}/scan-pick/',
               {'code': 'SS-P', 'bin_code': b.full_code, 'qty': 1}, format='json')
    assert r.status_code == 409
    assert InventoryItem.objects.get(pk=inv.pk).qty_on_hand == 20   # tồn nguyên vẹn
