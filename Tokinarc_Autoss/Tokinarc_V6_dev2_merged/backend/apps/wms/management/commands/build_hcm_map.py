"""
Dựng BẢN ĐỒ KHO HCM theo mã sản phẩm — cấu trúc VẬT LÝ thực tế.

Phân cấp: Zone (nhóm công năng) → Kệ K## (dãy, đi tới được)
          → Tầng T# (giới hạn để với tay được) → Ô ## (vị trí trên tầng).
  Mã ô:  HCM-A-K01-T1-03   (Kho-Zone-Kệ-Tầng-Ô)

  - Zone gom theo category (A thân súng&cáp, B béc-chụp-collet, C liner-ống-khí,
    D cách điện-dụng cụ, E súng hàn).
  - Mỗi mã (Part/Torch) chiếm đúng 1 ô; xếp lần lượt: đầy tầng dưới mới lên tầng trên,
    đầy 1 kệ mới sang kệ kế. Tồn cũ được giữ nguyên số lượng.

    python manage.py build_hcm_map                       # mặc định 4 tầng/kệ, 8 ô/tầng
    python manage.py build_hcm_map --levels 4 --per-level 8
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError

from apps.catalog.models import Part, Torch
from apps.wms.models import Bin, InventoryItem, Warehouse, Zone

ZONE_OF_CATEGORY = {
    # A — Thân súng & cáp
    'TorchBody': 'A', 'Handle': 'A', 'CableAssembly': 'A', 'PowerCable': 'A', 'InnerTube': 'A',
    # B — Béc, chụp & collet
    'Tip': 'B', 'TipBody': 'B', 'TipAdapter': 'B', 'Nozzle': 'B', 'CeramicNozzle': 'B',
    'LavaNozzle': 'B', 'Orifice': 'B', 'Collet': 'B', 'ColletBody': 'B',
    'GasLensColletBody': 'B', 'GasLensInsulator': 'B', 'WXCenterCeramic': 'B',
    'WXNozzleSpacer': 'B', 'WXNozzleAdapter': 'B', 'WXNozzleNut': 'B', 'WXNozzleSleeve': 'B',
    # C — Liner, ống & khí
    'Liner': 'C', 'liner': 'C', 'GuideTube': 'C', 'LinerORing': 'C', 'GasHose': 'C',
    # D — Cách điện, gioăng, điện cực & dụng cụ
    'InsulationCollar': 'D', 'InsulationSpacer': 'D', 'Insulator': 'D', 'BackCap': 'D',
    'ORing': 'D', 'Gasket': 'D', 'WaveWasher': 'D', 'TungstenElectrode': 'D', 'Tool': 'D',
    'RobotBracket': 'D', 'RobotFlange': 'D', 'AlignmentFixture': 'D', 'WXCoverRubber': 'D',
}
ZONE_NAMES = {
    'A': 'Thân súng & Cáp dẫn',
    'B': 'Béc hàn, Chụp khí & Collet',
    'C': 'Ruột gà (Liner), Ống & Dây khí',
    'D': 'Cách điện, Điện cực & Dụng cụ',
    'E': 'Súng hàn (nguyên bộ)',
}
DEFAULT_ZONE = 'D'


class Command(BaseCommand):
    help = "Dựng bản đồ kho HCM (zone/kệ/tầng/ô) theo mã sản phẩm."

    def add_arguments(self, parser):
        parser.add_argument('--levels', type=int, default=4, help='Số tầng tối đa mỗi kệ (với tay được).')
        parser.add_argument('--per-level', type=int, default=8, help='Số ô mỗi tầng.')

    @transaction.atomic
    def handle(self, levels, per_level, **kw):
        levels = max(1, levels)
        per_level = max(1, per_level)
        per_rack = levels * per_level            # sức chứa 1 kệ
        wh = Warehouse.objects.filter(code='HCM').first()
        if wh is None:
            raise CommandError("Không tìm thấy kho HCM.")

        # 1) Giữ tồn hiện có theo mã.
        old_qty: dict = {}
        for it in InventoryItem.objects.filter(bin__zone__warehouse=wh):
            key = ('p', it.part_id) if it.part_id else ('t', it.torch_id)
            old_qty[key] = old_qty.get(key, 0) + it.qty_on_hand
        InventoryItem.objects.filter(bin__zone__warehouse=wh).delete()
        # Dọn ô cũ (sơ đồ trước) để không tích luỹ qua nhiều lần dựng;
        # ô có lịch sử (movement/picklist/kiểm kê) bị PROTECT → bỏ qua, giữ lại.
        kept = 0
        for b in Bin.objects.filter(zone__warehouse=wh):
            try:
                b.delete()
            except ProtectedError:
                kept += 1

        # 2) Gom sản phẩm theo zone → category (giữ thứ tự theo MÃ).
        zone_cat: dict = defaultdict(lambda: defaultdict(list))
        for p in Part.objects.all().order_by('category', 'tokin_part_no'):
            cat = p.category or 'Khac'
            zone_cat[ZONE_OF_CATEGORY.get(cat, DEFAULT_ZONE)][cat].append(('p', p))
        for t in Torch.objects.all().order_by('family', 'model_code'):
            zone_cat['E'][t.family or 'Khac'].append(('t', t))

        # 3) Dựng zone → kệ → tầng → ô.
        n_zone = n_rack = n_bin = 0
        max_levels = 0
        for zcode in sorted(zone_cat):
            zone, _ = Zone.objects.update_or_create(
                warehouse=wh, code=zcode,
                defaults={'name': ZONE_NAMES.get(zcode, zcode),
                          'purpose': ZONE_NAMES.get(zcode, zcode)})
            n_zone += 1
            rack_no = 0
            for cat in sorted(zone_cat[zcode]):
                items = zone_cat[zcode][cat]
                # mỗi category bắt đầu ở kệ mới; chia thành các kệ sức chứa per_rack.
                for base in range(0, len(items), per_rack):
                    rack_no += 1
                    n_rack += 1
                    chunk = items[base:base + per_rack]
                    rack = f'K{rack_no:02d}'
                    for k, (kind, obj) in enumerate(chunk):
                        level = k // per_level + 1          # T1..T{levels}
                        pos   = k % per_level + 1
                        max_levels = max(max_levels, level)
                        rack_lv = f'{rack}-T{level}'
                        bin_code = f'{pos:02d}'
                        full = f'HCM-{zcode}-{rack_lv}-{bin_code}'
                        b, _ = Bin.objects.get_or_create(
                            zone=zone, rack=rack_lv, bin_code=bin_code,
                            defaults={'full_code': full, 'capacity': 1})
                        if b.full_code != full:
                            b.full_code = full; b.save(update_fields=['full_code'])
                        qty = old_qty.get((kind, obj.pk), 0)
                        InventoryItem.objects.create(
                            bin=b, part=obj if kind == 'p' else None,
                            torch=obj if kind == 't' else None, qty_on_hand=qty)
                        n_bin += 1

        self.stdout.write(self.style.SUCCESS(
            f"✅ Kho HCM: {n_zone} zone · {n_rack} kệ · {n_bin} ô "
            f"(tối đa {levels} tầng/kệ, {per_level} ô/tầng; thực dùng cao nhất {max_levels} tầng)."
            + (f" Giữ {kept} ô cũ có lịch sử." if kept else "")))
