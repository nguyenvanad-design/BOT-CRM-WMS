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


@pytest.fixture
def wh_mgr(db):
    return UserFactory(role='wh_manager')


@pytest.fixture
def auth_mgr(wh_mgr):
    c = APIClient(); c.force_authenticate(wh_mgr); return c


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
def test_scan_entry_count_sets_stock(auth, auth_mgr, part):
    BinFactory(full_code='HCM-A-R01-B06')
    auth.post('/api/v1/wms/inventory/scan-entry/',
              {'code': '002001', 'bin_code': 'HCM-A-R01-B06', 'qty': 100, 'mode': 'receive'},
              format='json')
    # NV kho thường KHÔNG được kiểm kê đặt lại tồn → 403
    assert auth.post('/api/v1/wms/inventory/scan-entry/',
                     {'code': '002001', 'bin_code': 'HCM-A-R01-B06', 'qty': 80, 'mode': 'count'},
                     format='json').status_code == 403
    # Quản lý kho mới được
    r = auth_mgr.post('/api/v1/wms/inventory/scan-entry/',
                      {'code': '002001', 'bin_code': 'HCM-A-R01-B06', 'qty': 80, 'mode': 'count'},
                      format='json')
    assert r.status_code == 200 and r.data['qty_on_hand'] == 80


@pytest.mark.django_db
def test_warehouse_staff_cannot_adjust(auth, part):
    """Nhân viên kho KHÔNG được điều chỉnh tồn (chỉ Quản lý kho+)."""
    b = BinFactory(full_code='HCM-A-R01-B20')
    r = auth.post('/api/v1/wms/inventory/adjust/',
                  {'bin': str(b.id), 'part': '002001', 'new_qty': 5, 'reason': 'adjust', 'note': ''},
                  format='json')
    assert r.status_code == 403


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


# ─── FIFO thật + Lot tracking khép kín ───────────────────────────────────────
@pytest.mark.django_db
def test_receive_creates_lot_and_received_at(part, wh_user):
    import datetime as dt
    from apps.wms.models import InventoryItem, Lot
    b = BinFactory(full_code='HCM-MIG-T1-B01')
    item = services.receive_stock(bin_obj=b, part=part, qty=50, user=wh_user,
                                  lot_no='LOT-A', lot_expires=dt.date(2030, 1, 1))
    assert item.received_at is not None                      # FIFO mốc nhập
    lot = Lot.objects.get(lot_no='LOT-A')
    assert lot.qty_remaining == 50 and lot.expires_at == dt.date(2030, 1, 1)
    # nhập thêm cùng lô → cộng dồn
    services.receive_stock(bin_obj=b, part=part, qty=20, user=wh_user, lot_no='LOT-A')
    lot.refresh_from_db(); assert lot.qty_remaining == 70


@pytest.mark.django_db
def test_fifo_picks_oldest_bin_first(part, wh_user):
    import datetime as dt
    from django.utils import timezone
    from apps.wms.models import (Bin, InventoryItem, OutboundLine, OutboundOrder,
                                 PickListItem, Warehouse, Zone)
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='MIG', name='MIG')
    b_old = Bin.objects.create(zone=z, rack='T1', bin_code='B01', full_code='HCM-MIG-T1-B01')
    b_new = Bin.objects.create(zone=z, rack='T1', bin_code='B02', full_code='HCM-MIG-T1-B02')
    # b_new nhập trước (cũ hơn về thời gian) nhưng mã ô lớn hơn → FIFO phải chọn b_new
    InventoryItem.objects.create(bin=b_new, part=part, qty_on_hand=10,
                                 received_at=timezone.now() - dt.timedelta(days=5))
    InventoryItem.objects.create(bin=b_old, part=part, qty_on_hand=10,
                                 received_at=timezone.now())
    ob = OutboundOrder.objects.create(code='OUT-F1', warehouse=wh, rule='FIFO',
                                      created_by=wh_user, updated_by=wh_user)
    OutboundLine.objects.create(outbound=ob, part=part, qty_ordered=5)
    services.generate_pick_list(ob)
    pick = PickListItem.objects.get(outbound_line__outbound=ob)
    assert pick.bin_id == b_new.id     # lấy ô nhập sớm nhất (FIFO theo thời gian)


@pytest.mark.django_db
def test_fefo_ship_decrements_lot(part, wh_user):
    import datetime as dt
    from apps.wms.models import (Bin, Lot, OutboundLine, OutboundOrder, Warehouse, Zone)
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='MIG', name='MIG')
    b = Bin.objects.create(zone=z, rack='T1', bin_code='B01', full_code='HCM-MIG-T1-B01')
    services.receive_stock(bin_obj=b, part=part, qty=30, user=wh_user,
                           lot_no='LOT-X', lot_expires=dt.date(2030, 6, 1))
    ob = OutboundOrder.objects.create(code='OUT-F2', warehouse=wh, rule='FEFO',
                                      created_by=wh_user, updated_by=wh_user)
    OutboundLine.objects.create(outbound=ob, part=part, qty_ordered=12)
    services.generate_pick_list(ob)
    services.confirm_pick_and_ship(ob, user=wh_user)
    assert Lot.objects.get(lot_no='LOT-X').qty_remaining == 18   # 30 - 12


@pytest.mark.django_db
def test_lot_expiring_filter(auth, part):
    import datetime as dt
    from apps.wms.models import Lot
    b = BinFactory(full_code='HCM-MIG-T1-B09')
    Lot.objects.create(lot_no='L-SOON', part=part, qty_remaining=5,
                       received_date=dt.date.today(), expires_at=dt.date.today() + dt.timedelta(days=10), bin=b)
    Lot.objects.create(lot_no='L-FAR', part=part, qty_remaining=5,
                       received_date=dt.date.today(), expires_at=dt.date.today() + dt.timedelta(days=200), bin=b)
    r = auth.get('/api/v1/wms/lots/?expiring_days=30')
    codes = [x['lot_no'] for x in (r.data['results'] if 'results' in r.data else r.data)]
    assert 'L-SOON' in codes and 'L-FAR' not in codes


# ─── build_zones: dựng zone theo nhóm sản phẩm + dời tồn ─────────────────────
@pytest.mark.django_db
def test_build_zones_creates_taxonomy_and_relocates(wh_user):
    from django.core.management import call_command
    from apps.catalog.models import Part, Torch
    from apps.wms.models import Bin, InventoryItem, SerialNumber, Warehouse, Zone
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z0 = Zone.objects.create(warehouse=wh, code='OLD', name='Old')
    old = Bin.objects.create(zone=z0, rack='R', bin_code='B', full_code='HCM-OLD-R-B')
    tip = Part.objects.create(tokin_part_no='T-TIP', category='Tip', display_name_vi='Bép')
    InventoryItem.objects.create(bin=old, part=tip, qty_on_hand=7)
    torch = Torch.objects.create(model_code='RB-1', display_name_vi='Súng hàn robot RB-1',
                                 ecosystem='N', body_type='RR')
    sn = SerialNumber.objects.create(serial='SNR-1', torch=torch, bin=old, status='in_stock')

    call_command('build_zones', '--warehouse', 'HCM')

    # 8 zone chuẩn được tạo
    assert Zone.objects.filter(warehouse=wh, code='SUNG').exists()
    assert Zone.objects.filter(warehouse=wh).count() >= 8
    # Tip → zone MIG / tầng T1
    inv = InventoryItem.objects.get(part=tip)
    assert inv.bin.zone.code == 'MIG' and inv.bin.rack == 'T1' and inv.qty_on_hand == 7
    # Súng robot → zone SUNG / tầng T3
    sn.refresh_from_db()
    assert sn.bin.zone.code == 'SUNG' and sn.bin.rack == 'T3'


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
def test_cycle_count_scan_and_apply(auth, auth_mgr, part, wh_user):
    from apps.wms.models import Bin, InventoryItem, Warehouse, Zone
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='A', name='A')
    b = Bin.objects.create(zone=z, rack='R01', bin_code='B3', full_code='HCM-A-R01-B3')
    InventoryItem.objects.create(bin=b, part=part, qty_on_hand=100)
    cc = auth.post('/api/v1/wms/cycle-counts/', {'warehouse': str(wh.id)}, format='json').data
    # NV kho tạo phiên + quét đếm (nghiệp vụ)
    r = auth.post(f"/api/v1/wms/cycle-counts/{cc['id']}/scan/",
                  {'code': '002001', 'bin_code': 'HCM-A-R01-B3', 'counted_qty': 92}, format='json')
    assert r.data['system_qty'] == 100 and r.data['diff'] == -8
    # NV kho KHÔNG được duyệt (apply) → 403
    assert auth.post(f"/api/v1/wms/cycle-counts/{cc['id']}/apply/").status_code == 403
    # Quản lý kho duyệt chênh lệch
    ra = auth_mgr.post(f"/api/v1/wms/cycle-counts/{cc['id']}/apply/")
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
def test_ops_kpi(auth, auth_mgr, part, wh_user):
    """KPI vận hành: NV kho bị chặn; Quản lý kho xem được + có số liệu."""
    from apps.wms.models import Bin, Warehouse, Zone
    wh = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='MIG', name='MIG')
    b = Bin.objects.create(zone=z, rack='T1', bin_code='B01', full_code='HCM-MIG-T1-B01')
    services.receive_stock(bin_obj=b, part=part, qty=40, user=wh_user)
    # NV kho thường → 403
    assert auth.get('/api/v1/wms/ops-kpi/?warehouse=HCM').status_code == 403
    # Quản lý kho → 200 + số liệu nhập + tồn theo zone
    r = auth_mgr.get('/api/v1/wms/ops-kpi/?warehouse=HCM&days=30')
    assert r.status_code == 200
    assert r.data['inbound']['qty'] == 40
    assert any(z['zone'] == 'MIG' and z['qty'] == 40 for z in r.data['by_zone'])
    assert 'inventory_turnover' in r.data and r.data['on_hand_total'] == 40


@pytest.mark.django_db
def test_warehouse_manager_can_adjust(auth_mgr, part):
    """Quản lý kho (wh_manager) được điều chỉnh tồn."""
    b = BinFactory()
    r = auth_mgr.post('/api/v1/wms/inventory/adjust/',
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
