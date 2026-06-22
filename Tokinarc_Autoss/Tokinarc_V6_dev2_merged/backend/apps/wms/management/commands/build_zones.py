"""
Tokinarc — apps/wms/management/commands/build_zones.py

Dựng lại cấu trúc ZONE/TẦNG/Ô cho kho theo dữ liệu sản phẩm (v20):
  - Zone = nhóm sản phẩm (Súng hàn, Tiêu hao MIG, Tiêu hao TIG, ...).
  - Tầng (rack) = phân loại con trong zone (vd Súng hàn: cầm tay / TIG / robot).
  - Ô (bin) = vị trí cụ thể trong tầng.
Mặc định có RELOCATE: dời tồn + serial hiện có về đúng ô theo nhóm sản phẩm.

Dùng:
  python manage.py build_zones                 # kho mặc định HCM, dời tồn
  python manage.py build_zones --warehouse HCM --no-relocate
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.wms.models import (
    Bin, InboundLine, InventoryItem, Lot, PickListItem, SerialNumber,
    StockMovement, Warehouse, Zone,
)

BINS_PER_RACK = 4

# ── Định nghĩa zone + tầng (rack). Mỗi rack: (mã, tên tầng) ───────────────────
ZONES = [
    ('SUNG', 'Súng hàn', 'Súng hàn', [
        ('T1', 'Cầm tay MIG/MAG'), ('T2', 'Cầm tay TIG'),
        ('T3', 'Robot / Bán tự động'), ('T4', 'Làm mát nước'),
    ]),
    ('MIG', 'Tiêu hao MIG/MAG', 'Vật tư tiêu hao MIG', [
        ('T1', 'Bép hàn (Tip)'), ('T2', 'Chụp khí (Nozzle)'), ('T3', 'Ống/đầu dẫn'),
    ]),
    ('TIG', 'Tiêu hao TIG', 'Vật tư tiêu hao TIG', [
        ('T1', 'Điện cực Tungsten'), ('T2', 'Chụp sứ'), ('T3', 'Collet & Gas lens'),
    ]),
    ('THAN', 'Thân & Tay súng', 'Thân súng', [
        ('T1', 'Thân súng'), ('T2', 'Tay cầm & ống dẫn'),
    ]),
    ('CAP', 'Cáp & Ống dẫn', 'Cáp - ống', [
        ('T1', 'Dây lót (Liner)'), ('T2', 'Cáp điện'), ('T3', 'Ống khí'),
    ]),
    ('ROBOT', 'Robot & Giá đỡ', 'Phụ kiện robot', [
        ('T1', 'Giá đỡ & Mặt bích'),
    ]),
    ('LK', 'Linh kiện & Cách điện', 'Linh kiện nhỏ', [
        ('T1', 'Gioăng / Đệm'), ('T2', 'Cách điện'),
    ]),
    ('WX', 'Phụ kiện WX & Dụng cụ', 'WX - dụng cụ', [
        ('T1', 'Bộ WX'), ('T2', 'Dụng cụ'),
    ]),
]

# ── Map category phụ tùng → (zone, tầng) ──────────────────────────────────────
CAT_MAP = {
    'Tip': ('MIG', 'T1'), 'TipBody': ('THAN', 'T1'), 'TipAdapter': ('MIG', 'T1'),
    'Nozzle': ('MIG', 'T2'), 'LavaNozzle': ('MIG', 'T2'),
    'InnerTube': ('MIG', 'T3'), 'Orifice': ('MIG', 'T3'),
    'TungstenElectrode': ('TIG', 'T1'),
    'CeramicNozzle': ('TIG', 'T2'), 'WXCenterCeramic': ('WX', 'T1'),
    'Collet': ('TIG', 'T3'), 'ColletBody': ('TIG', 'T3'),
    'GasLensColletBody': ('TIG', 'T3'), 'GasLensInsulator': ('TIG', 'T3'),
    'BackCap': ('TIG', 'T3'),
    'TorchBody': ('THAN', 'T1'), 'Handle': ('THAN', 'T2'), 'GuideTube': ('THAN', 'T2'),
    'Liner': ('CAP', 'T1'), 'LinerORing': ('CAP', 'T1'),
    'PowerCable': ('CAP', 'T2'), 'CableAssembly': ('CAP', 'T2'), 'GasHose': ('CAP', 'T3'),
    'RobotBracket': ('ROBOT', 'T1'), 'RobotFlange': ('ROBOT', 'T1'),
    'InsulationCollar': ('ROBOT', 'T1'),
    'ORing': ('LK', 'T1'), 'Gasket': ('LK', 'T1'), 'WaveWasher': ('LK', 'T1'),
    'InsulationSpacer': ('LK', 'T1'), 'Insulator': ('LK', 'T2'),
    'Tool': ('WX', 'T2'), 'AlignmentFixture': ('WX', 'T2'),
    'WXNozzleSpacer': ('WX', 'T1'), 'WXNozzleAdapter': ('WX', 'T1'),
    'WXNozzleNut': ('WX', 'T1'), 'WXCoverRubber': ('WX', 'T1'),
    'WXNozzleSleeve': ('WX', 'T1'),
}
DEFAULT_TARGET = ('LK', 'T1')   # category lạ → linh kiện
ROBOT_BODY = {'RR', 'RX', 'RS', 'RW', 'ALW'}


def torch_target(t) -> tuple[str, str]:
    """Phân tầng súng hàn theo dữ liệu."""
    name = (t.display_name_vi or '').lower()
    if 'robot' in name or (t.body_type or '') in ROBOT_BODY:
        return ('SUNG', 'T3')
    if (t.ecosystem or '') == 'TIG':
        return ('SUNG', 'T2')
    if (t.cooling or '') == 'water':
        return ('SUNG', 'T4')
    return ('SUNG', 'T1')   # MIG/MAG cầm tay


class Command(BaseCommand):
    help = "Dựng lại zone/tầng/ô theo nhóm sản phẩm + dời tồn về đúng ô."

    def add_arguments(self, parser):
        parser.add_argument('--warehouse', default='HCM')
        parser.add_argument('--no-relocate', action='store_true')
        parser.add_argument('--purge-old', action='store_true',
                            help='Xóa các zone KHÔNG thuộc taxonomy mới (vd A/B/C) sau khi dời hàng.')

    @transaction.atomic
    def handle(self, *, warehouse, no_relocate, purge_old, **kw):
        wh, _ = Warehouse.objects.get_or_create(
            code=warehouse, defaults={'name': f'Kho {warehouse}', 'is_active': True,
                                      'is_default': True})

        first_bin: dict[tuple[str, str], Bin] = {}
        n_zone = n_bin = 0
        for zcode, zname, purpose, racks in ZONES:
            zone, _ = Zone.objects.get_or_create(
                warehouse=wh, code=zcode, defaults={'name': zname, 'purpose': purpose})
            if zone.name != zname or zone.purpose != purpose:
                zone.name, zone.purpose = zname, purpose
                zone.save(update_fields=['name', 'purpose'])
            n_zone += 1
            for rcode, rname in racks:
                for i in range(1, BINS_PER_RACK + 1):
                    full = f'{warehouse}-{zcode}-{rcode}-B{i:02d}'
                    b, created = Bin.objects.get_or_create(
                        zone=zone, rack=rcode, bin_code=f'B{i:02d}',
                        defaults={'full_code': full})
                    if created:
                        n_bin += 1
                    first_bin.setdefault((zcode, rcode), b)

        self.stdout.write(self.style.SUCCESS(
            f'Đã dựng {n_zone} zone, +{n_bin} ô mới tại kho {warehouse}.'))
        for zcode, zname, _p, racks in ZONES:
            self.stdout.write(f'  • {zcode} — {zname}: ' +
                              ', '.join(f'{rc}={rn}' for rc, rn in racks))

        if no_relocate:
            return

        moved = 0
        for item in InventoryItem.objects.select_related('part', 'torch'):
            if item.part_id:
                zc, rc = CAT_MAP.get(item.part.category, DEFAULT_TARGET)
            elif item.torch_id:
                zc, rc = torch_target(item.torch)
            else:
                continue
            target = first_bin.get((zc, rc))
            if not target or item.bin_id == target.id:
                continue
            dup = (InventoryItem.objects
                   .filter(bin=target, part=item.part, torch=item.torch)
                   .exclude(pk=item.pk).first())
            if dup:
                dup.qty_on_hand += item.qty_on_hand
                dup.qty_reserved += item.qty_reserved
                dup.save(update_fields=['qty_on_hand', 'qty_reserved'])
                item.delete()
            else:
                item.bin = target
                item.save(update_fields=['bin'])
            moved += 1

        s_moved = 0
        for sn in SerialNumber.objects.select_related('torch'):
            if not sn.torch_id:
                continue
            zc, rc = torch_target(sn.torch)
            target = first_bin.get((zc, rc))
            if target and sn.bin_id != target.id:
                sn.bin = target
                sn.save(update_fields=['bin'])
                s_moved += 1

        self.stdout.write(self.style.SUCCESS(
            f'Đã dời {moved} dòng tồn + {s_moved} serial về đúng zone/tầng.'))

        if purge_old:
            new_codes = {z[0] for z in ZONES}
            old_zones = Zone.objects.filter(warehouse=wh).exclude(code__in=new_codes)
            old_bins = Bin.objects.filter(zone__in=old_zones)
            # Gỡ/xóa các tham chiếu chặn xóa bin (dev: xóa lịch sử kho ở bin cũ).
            SerialNumber.objects.filter(bin__in=old_bins).update(bin=None)
            InboundLine.objects.filter(target_bin__in=old_bins).update(target_bin=None)
            PickListItem.objects.filter(bin__in=old_bins).delete()
            StockMovement.objects.filter(bin__in=old_bins).delete()
            Lot.objects.filter(bin__in=old_bins).delete()
            InventoryItem.objects.filter(bin__in=old_bins).delete()   # còn sót
            names = list(old_zones.values_list('code', flat=True))
            old_zones.delete()   # cascade xóa bin
            self.stdout.write(self.style.WARNING(
                f'Đã XÓA {len(names)} zone cũ: {", ".join(names) or "—"}.'))
