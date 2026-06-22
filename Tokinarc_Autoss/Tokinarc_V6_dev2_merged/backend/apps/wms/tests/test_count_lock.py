"""Khóa ô/mã khi đang kiểm kê: chặn xuất/nhập, cho lại sau khi áp dụng."""
import pytest

from apps.accounts.models import Role, User
from apps.wms import services


@pytest.mark.django_db
def test_open_count_locks_issue_and_receive():
    from apps.catalog.models import Part
    from apps.wms.models import (Bin, CycleCount, CycleCountLine, InventoryItem,
                                 Warehouse, Zone)
    u = User.objects.create(username='cl_kho', role=Role.WAREHOUSE)
    part = Part.objects.create(tokin_part_no='CL-P', category='Tip', display_name_vi='Bép')
    w = Warehouse.objects.create(code='HCM', name='K', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=w, code='MIG', name='MIG')
    b = Bin.objects.create(zone=z, rack='T1', bin_code='B01', full_code='HCM-MIG-T1-B01')
    InventoryItem.objects.create(bin=b, part=part, qty_on_hand=50)
    cc = CycleCount.objects.create(code='KK-1', warehouse=w, status='open',
                                   created_by=u, updated_by=u)
    CycleCountLine.objects.create(session=cc, bin=b, part=part, system_qty=50)

    # Đang đếm → xuất/nhập bị khóa
    with pytest.raises(services.CountLockError):
        services.issue_stock(bin_obj=b, part=part, qty=5, user=u)
    with pytest.raises(services.CountLockError):
        services.receive_stock(bin_obj=b, part=part, qty=5, user=u)

    # Áp dụng xong (status applied) → hết khóa
    cc.status = 'applied'; cc.save(update_fields=['status'])
    item = services.issue_stock(bin_obj=b, part=part, qty=5, user=u)
    assert item.qty_on_hand == 45
