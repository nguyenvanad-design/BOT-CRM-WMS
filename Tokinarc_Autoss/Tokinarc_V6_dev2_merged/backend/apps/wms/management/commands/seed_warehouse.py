"""
Tokinarc V6.C — apps/wms/management/commands/seed_warehouse.py

Tạo kho HCM mặc định + zone/bin cơ bản. Multi-warehouse sẵn sàng: thêm kho mới
chỉ cần gọi lại với --code/--name khác (FE tự hiện switcher khi >1 kho).

    python manage.py seed_warehouse                       # tạo HCM mặc định
    python manage.py seed_warehouse --code HN --name "Kho Hà Nội"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.wms.models import Bin, Warehouse, Zone

# Zone mặc định: vật tư tiêu hao + súng hàn + khu nhận hàng
DEFAULT_ZONES = [
    ('A', 'Vật tư tiêu hao', 'Tip/Nozzle/Orifice — pick nhanh'),
    ('B', 'Súng hàn', 'Torch nguyên chiếc, theo serial'),
    ('C', 'Khu nhận hàng', 'Staging trước putaway'),
]


class Command(BaseCommand):
    help = "Seed kho + zone + bin cơ bản (mặc định HCM)."

    def add_arguments(self, parser):
        parser.add_argument('--code', default='HCM')
        parser.add_argument('--name', default='Kho Hồ Chí Minh')
        parser.add_argument('--racks', type=int, default=3)
        parser.add_argument('--bins-per-rack', type=int, default=10)
        parser.add_argument('--default', action='store_true',
                            help='Đánh dấu là kho mặc định (auto khi FE chỉ 1 kho)')

    @transaction.atomic
    def handle(self, code, name, racks, bins_per_rack, default, **kw):
        is_first = not Warehouse.objects.exists()
        wh, created = Warehouse.objects.update_or_create(
            code=code, defaults={'name': name, 'is_active': True,
                                 'is_default': default or is_first})
        n_bins = 0
        for zcode, zname, purpose in DEFAULT_ZONES:
            zone, _ = Zone.objects.update_or_create(
                warehouse=wh, code=zcode,
                defaults={'name': zname, 'purpose': purpose})
            for r in range(1, racks + 1):
                for b in range(1, bins_per_rack + 1):
                    full = f"{code}-{zcode}-R{r:02d}-B{b:02d}"
                    _, made = Bin.objects.update_or_create(
                        zone=zone, rack=f"R{r:02d}", bin_code=f"B{b:02d}",
                        defaults={'full_code': full})
                    n_bins += 1 if made else 0
        self.stdout.write(self.style.SUCCESS(
            f"✅ Kho {code} ({'tạo mới' if created else 'cập nhật'}), "
            f"{len(DEFAULT_ZONES)} zone, ~{racks * bins_per_rack * len(DEFAULT_ZONES)} bin."))
