"""
Tokinarc V6.C — apps/wms/tests/test_wms.py

Theo pattern apps/crm/tests: factory-boy + pytest-django + APIClient.
Phủ: multi-warehouse filter, part/torch XOR constraint, permission (customer bị
chặn, warehouse ghi được), adjust/transfer qua services, low_stock filter.
"""
from __future__ import annotations

import factory
import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.catalog.models import Part, Torch
from apps.wms import services
from apps.wms.models import (
    Bin, InventoryItem, Warehouse, Zone,
)

User = get_user_model()


# ─── Factories ───────────────────────────────────────────────────────────────
class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
    username = factory.Sequence(lambda n: f'wh{n}')
    role     = 'warehouse'


class WarehouseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Warehouse
    code = factory.Sequence(lambda n: f'W{n}')
    name = factory.Sequence(lambda n: f'Kho {n}')
    is_active = True


class ZoneFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Zone
    warehouse = factory.SubFactory(WarehouseFactory)
    code = factory.Sequence(lambda n: f'Z{n}')
    name = 'Zone'


class BinFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Bin
    zone = factory.SubFactory(ZoneFactory)
    rack = 'R01'
    bin_code = factory.Sequence(lambda n: f'B{n:02d}')
    full_code = factory.Sequence(lambda n: f'W-Z-R01-B{n:02d}')


@pytest.fixture
def part(db):
    return Part.objects.create(tokin_part_no='002001', category='Tip',
                               display_name_vi='Béc hàn 002001')


@pytest.fixture
def torch(db):
    return Torch.objects.create(model_code='TK-508RR', display_name_vi='Súng 508RR')


@pytest.fixture
def wh_user(db):
    return UserFactory(role='warehouse')


@pytest.fixture
def customer_user(db):
    return UserFactory(role='customer')


@pytest.fixture
def auth(wh_user):
    c = APIClient()
    c.force_authenticate(wh_user)
    return c


# ─── Scan-entry: quét điện thoại để nhập dữ liệu ─────────────────────────────
@pytest.mark.django_db
def test_scan_entry_receive_adds_stock(auth, part):
    b = BinFactory(full_code='HCM-A-R01-B05')
    r = auth.post('/api/v1/wms/inventory/scan-entry/',
                  {'code': '002001', 'bin_code': 'HCM-A-R01-B05', 'qty': 10, 'mode': 'receive'},
                  format='json')
    assert r.status_code == 200
    assert r.data['qty_on_hand'] == 10
    # quét lần 2 cộng dồn
    r2 = auth.post('/api/v1/wms/inventory/scan-entry/',
                   {'code': '002001', 'bin_code': 'HCM-A-R01-B05', 'qty': 5, 'mode': 'receive'},
                   format='json')
    assert r2.data['qty_on_hand'] == 15
    assert InventoryItem.objects.get(bin=b, part=part).qty_on_hand == 15


@pytest.mark.django_db
def test_scan_entry_count_sets_stock(auth, part):
    BinFactory(full_code='HCM-A-R01-B06')
    auth.post('/api/v1/wms/inventory/scan-entry/',
              {'code': '002001', 'bin_code': 'HCM-A-R01-B06', 'qty': 100, 'mode': 'receive'},
              format='json')
    # kiểm kê: đếm thực tế chỉ còn 80 → set tồn = 80
    r = auth.post('/api/v1/wms/inventory/scan-entry/',
                  {'code': '002001', 'bin_code': 'HCM-A-R01-B06', 'qty': 80, 'mode': 'count'},
                  format='json')
    assert r.status_code == 200
    assert r.data['qty_on_hand'] == 80


@pytest.mark.django_db
def test_scan_entry_receive_torch(auth, torch):
    BinFactory(full_code='HCM-A-R01-T01')
    r = auth.post('/api/v1/wms/inventory/scan-entry/',
                  {'code': 'TK-508RR', 'bin_code': 'HCM-A-R01-T01', 'qty': 3, 'mode': 'receive'},
                  format='json')
    assert r.status_code == 200 and r.data['qty_on_hand'] == 3
    assert r.data['part_no'] == 'TK-508RR'


@pytest.mark.django_db
def test_scan_entry_issue_deducts_stock(auth, part):
    BinFactory(full_code='HCM-A-R01-B09')
    auth.post('/api/v1/wms/inventory/scan-entry/',
              {'code': '002001', 'bin_code': 'HCM-A-R01-B09', 'qty': 30, 'mode': 'receive'},
              format='json')
    r = auth.post('/api/v1/wms/inventory/scan-entry/',
                  {'code': '002001', 'bin_code': 'HCM-A-R01-B09', 'qty': 12, 'mode': 'issue'},
                  format='json')
    assert r.status_code == 200 and r.data['qty_on_hand'] == 18
    # xuất quá tồn → 409
    r2 = auth.post('/api/v1/wms/inventory/scan-entry/',
                   {'code': '002001', 'bin_code': 'HCM-A-R01-B09', 'qty': 999, 'mode': 'issue'},
                   format='json')
    assert r2.status_code == 409


@pytest.mark.django_db
def test_scan_entry_unknown_part_or_bin(auth, part):
    BinFactory(full_code='HCM-A-R01-B07')
    assert auth.post('/api/v1/wms/inventory/scan-entry/',
                     {'code': 'XXXX', 'bin_code': 'HCM-A-R01-B07', 'qty': 1},
                     format='json').status_code == 404
    assert auth.post('/api/v1/wms/inventory/scan-entry/',
                     {'code': '002001', 'bin_code': 'KHONG-CO', 'qty': 1},
                     format='json').status_code == 404


@pytest.mark.django_db
def test_scan_entry_blocked_for_customer(customer_user, part):
    BinFactory(full_code='HCM-A-R01-B08')
    c = APIClient(); c.force_authenticate(customer_user)
    r = c.post('/api/v1/wms/inventory/scan-entry/',
               {'code': '002001', 'bin_code': 'HCM-A-R01-B08', 'qty': 1}, format='json')
    assert r.status_code in (403, 401)


# ─── Scan theo phiếu + kiểm kê (hoàn thiện scan) ─────────────────────────────
@pytest.mark.django_db
def test_inbound_scan_receive_then_confirm(auth, part, wh_user):
    from apps.wms.models import Bin, InboundLine, InboundOrder, InventoryItem, Warehouse, Zone
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='A', name='A')
    b = Bin.objects.create(zone=z, rack='R01', bin_code='B1', full_code='HCM-A-R01-B1')
    io = InboundOrder.objects.create(code='IN-1', warehouse=wh, created_by=wh_user, updated_by=wh_user)
    InboundLine.objects.create(inbound=io, part=part, qty_expected=10, target_bin=b)
    # quét nhận 6 rồi 4
    auth.post(f'/api/v1/wms/inbound/{io.id}/scan-receive/', {'code': '002001', 'qty': 6}, format='json')
    r = auth.post(f'/api/v1/wms/inbound/{io.id}/scan-receive/', {'code': '002001', 'qty': 4}, format='json')
    assert r.data['received'] == 10 and r.data['all_done'] is True
    # confirm → cộng tồn đúng số đã nhận
    auth.post(f'/api/v1/wms/inbound/{io.id}/confirm/')
    assert InventoryItem.objects.get(bin=b, part=part).qty_on_hand == 10


@pytest.mark.django_db
def test_outbound_scan_pick_deducts(auth, part, wh_user):
    from apps.wms.models import (Bin, InventoryItem, OutboundLine, OutboundOrder,
                                 Warehouse, Zone)
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='A', name='A')
    b = Bin.objects.create(zone=z, rack='R01', bin_code='B2', full_code='HCM-A-R01-B2')
    InventoryItem.objects.create(bin=b, part=part, qty_on_hand=20)
    ob = OutboundOrder.objects.create(code='OUT-1', warehouse=wh, created_by=wh_user, updated_by=wh_user)
    OutboundLine.objects.create(outbound=ob, part=part, qty_ordered=5)
    r = auth.post(f'/api/v1/wms/outbound/{ob.id}/scan-pick/',
                  {'code': '002001', 'bin_code': 'HCM-A-R01-B2', 'qty': 5}, format='json')
    assert r.status_code == 200 and r.data['all_done'] is True
    assert InventoryItem.objects.get(bin=b, part=part).qty_on_hand == 15


@pytest.mark.django_db
def test_cycle_count_scan_and_apply(auth, part, wh_user):
    from apps.wms.models import Bin, InventoryItem, Warehouse, Zone
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='A', name='A')
    b = Bin.objects.create(zone=z, rack='R01', bin_code='B3', full_code='HCM-A-R01-B3')
    InventoryItem.objects.create(bin=b, part=part, qty_on_hand=100)
    cc = auth.post('/api/v1/wms/cycle-counts/', {'warehouse': str(wh.id)}, format='json').data
    # đếm thực tế 92 (thiếu 8)
    r = auth.post(f"/api/v1/wms/cycle-counts/{cc['id']}/scan/",
                  {'code': '002001', 'bin_code': 'HCM-A-R01-B3', 'counted_qty': 92}, format='json')
    assert r.data['system_qty'] == 100 and r.data['diff'] == -8
    ra = auth.post(f"/api/v1/wms/cycle-counts/{cc['id']}/apply/")
    assert ra.data['total_diff'] == -8
    assert InventoryItem.objects.get(bin=b, part=part).qty_on_hand == 92


# ─── N1.3 Serial history (2 chiều, gồm ticket) ───────────────────────────────
@pytest.mark.django_db
def test_serial_history_includes_tickets(auth, torch):
    import datetime as dt

    from apps.crm.models import Customer, Ticket
    from apps.wms.models import SerialNumber
    cust = Customer.objects.create(code='KH-SN1', name='ACME', segment='factory',
                                   owner=UserFactory(role='sales'))
    sn = SerialNumber.objects.create(serial='SN-12345', torch=torch, status='sold',
                                     sold_to_customer=cust, sold_order='HD-1',
                                     warranty_until=dt.date(2030, 1, 1))
    Ticket.objects.create(code='TK-1', customer=cust, title='Lỗi mỏ', serial_no='SN-12345',
                          created_owner=UserFactory(role='service'))
    r = auth.get(f'/api/v1/wms/serials/{sn.id}/history/')
    assert r.status_code == 200
    assert r.data['sold_to_customer'] == 'ACME'
    assert r.data['warranty_state'] == 'valid'
    assert len(r.data['tickets']) == 1 and r.data['tickets'][0]['code'] == 'TK-1'


# ─── Constraint: part XOR torch ──────────────────────────────────────────────
@pytest.mark.django_db
def test_inventory_requires_exactly_one_of_part_torch(part, torch):
    b = BinFactory()
    # cả hai null → vi phạm
    with pytest.raises(IntegrityError):
        InventoryItem.objects.create(bin=b, part=None, torch=None, qty_on_hand=1)


@pytest.mark.django_db
def test_inventory_both_set_rejected(part, torch):
    b = BinFactory()
    with pytest.raises(IntegrityError):
        InventoryItem.objects.create(bin=b, part=part, torch=torch, qty_on_hand=1)


# ─── Services: adjust + movement ─────────────────────────────────────────────
@pytest.mark.django_db
def test_adjust_creates_movement(part, wh_user):
    b = BinFactory()
    item = services.adjust_stock(bin_obj=b, part=part, new_qty=50,
                                 reason='adjust', user=wh_user)
    assert item.qty_on_hand == 50
    from apps.wms.models import StockMovement
    mv = StockMovement.objects.get()
    assert mv.delta == 50 and mv.reason == 'adjust'


@pytest.mark.django_db
def test_transfer_moves_stock(part, wh_user):
    b1, b2 = BinFactory(), BinFactory()
    services.adjust_stock(bin_obj=b1, part=part, new_qty=30, reason='adjust', user=wh_user)
    services.transfer_stock(from_bin=b1, to_bin=b2, part=part, qty=10, user=wh_user)
    assert InventoryItem.objects.get(bin=b1, part=part).qty_on_hand == 20
    assert InventoryItem.objects.get(bin=b2, part=part).qty_on_hand == 10


@pytest.mark.django_db
def test_transfer_insufficient_raises(part, wh_user):
    b1, b2 = BinFactory(), BinFactory()
    services.adjust_stock(bin_obj=b1, part=part, new_qty=5, reason='adjust', user=wh_user)
    with pytest.raises(services.InsufficientStock):
        services.transfer_stock(from_bin=b1, to_bin=b2, part=part, qty=10, user=wh_user)


# ─── API: multi-warehouse filter ─────────────────────────────────────────────
@pytest.mark.django_db
def test_inventory_filtered_by_warehouse(auth, part):
    wh1 = WarehouseFactory(code='HCM')
    wh2 = WarehouseFactory(code='HN')
    z1 = ZoneFactory(warehouse=wh1); z2 = ZoneFactory(warehouse=wh2)
    b1 = BinFactory(zone=z1, full_code='HCM-A-R01-B01')
    b2 = BinFactory(zone=z2, full_code='HN-A-R01-B01')
    InventoryItem.objects.create(bin=b1, part=part, qty_on_hand=10)
    InventoryItem.objects.create(bin=b2, part=part, qty_on_hand=20)

    r = auth.get('/api/v1/wms/inventory/?warehouse=HCM')
    assert r.status_code == 200
    codes = {row['warehouse_code'] for row in r.data['results']}
    assert codes == {'HCM'}


@pytest.mark.django_db
def test_low_stock_filter(auth, part):
    b = BinFactory()
    InventoryItem.objects.create(bin=b, part=part, qty_on_hand=2, min_level=5)
    r = auth.get('/api/v1/wms/inventory/?low_stock=true')
    assert r.status_code == 200
    assert len(r.data['results']) == 1


# ─── Permission: customer bị chặn, warehouse ghi được ────────────────────────
@pytest.mark.django_db
def test_customer_blocked_from_wms(customer_user, part):
    c = APIClient(); c.force_authenticate(customer_user)
    r = c.get('/api/v1/wms/inventory/')
    assert r.status_code == 403


@pytest.mark.django_db
def test_warehouse_can_adjust(auth, part):
    b = BinFactory()
    r = auth.post('/api/v1/wms/inventory/adjust/',
                  {'bin': b.id, 'part': part.pk, 'new_qty': 100, 'reason': 'adjust'},
                  format='json')
    assert r.status_code == 200
    assert r.data['qty_on_hand'] == 100


@pytest.mark.django_db
def test_sales_cannot_adjust(part):
    sales = UserFactory(role='sales')
    c = APIClient(); c.force_authenticate(sales)
    b = BinFactory()
    r = c.post('/api/v1/wms/inventory/adjust/',
               {'bin': b.id, 'part': part.pk, 'new_qty': 5}, format='json')
    assert r.status_code == 403
