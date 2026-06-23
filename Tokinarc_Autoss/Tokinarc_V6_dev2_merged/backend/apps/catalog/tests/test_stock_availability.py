"""Bot khách đọc tình trạng còn hàng (thô, có key)."""
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.catalog.models import Part


def _part(no):
    return Part.objects.create(tokin_part_no=no, category='Tip', display_name_vi=f'Bép {no}')


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='k', PUBLIC_LOW_STOCK_THRESHOLD=10)
def test_stock_status_coarse():
    from apps.wms.models import Bin, InventoryItem, Warehouse, Zone
    w = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=w, code='MIG', name='MIG')
    b = Bin.objects.create(zone=z, rack='T1', bin_code='B01', full_code='HCM-MIG-T1-B01')
    p_in = _part('IN-1'); p_low = _part('LOW-1'); p_out = _part('OUT-1'); _part('NONE-1')
    InventoryItem.objects.create(bin=b, part=p_in, qty_on_hand=100, qty_reserved=0)
    InventoryItem.objects.create(bin=b, part=p_low, qty_on_hand=8, qty_reserved=0)
    InventoryItem.objects.create(bin=b, part=p_out, qty_on_hand=5, qty_reserved=5)

    c = APIClient()
    r = c.get('/api/v1/catalog/stock-availability/?parts=IN-1,LOW-1,OUT-1,NONE-1,GHOST',
              HTTP_X_INTAKE_KEY='k')
    assert r.status_code == 200
    st = {x['part']: x['status'] for x in r.data['results']}
    assert st['IN-1'] == 'in_stock'
    assert st['LOW-1'] == 'low_stock'
    assert st['OUT-1'] == 'out_of_stock'   # 5-5=0
    assert st['NONE-1'] == 'contact'       # part có nhưng chưa có tồn
    assert st['GHOST'] == 'contact'        # part không tồn tại
    # KHÔNG lộ số lượng chính xác
    assert all('qty' not in x and 'qty_on_hand' not in x for x in r.data['results'])


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='k')
def test_stock_requires_key():
    c = APIClient()
    r = c.get('/api/v1/catalog/stock-availability/?parts=X', HTTP_X_INTAKE_KEY='wrong')
    assert r.status_code == 401
