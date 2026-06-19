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
