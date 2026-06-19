"""
Tokinarc V6 — apps/wms/management/commands/seed_wms_demo.py

Seed dữ liệu WMS mẫu (idempotent). Tự tạo vài Part/Torch tối thiểu (vì catalog
seed lớn chưa chạy) để có FK cho tồn kho/serial.

Chạy: python manage.py seed_wms_demo
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Part, Torch
from apps.crm.models import Customer
from apps.wms.models import (
    ASN, Bin, InboundLine, InboundOrder, InventoryItem, Lot, MovementReason,
    OutboundLine, OutboundOrder, SerialNumber, StockMovement, Warehouse, Zone,
)


class Command(BaseCommand):
    help = 'Seed dữ liệu WMS mẫu (idempotent).'

    @transaction.atomic
    def handle(self, *args, **opts):
        user = User.objects.filter(username='kho1').first() or User.objects.filter(role='warehouse').first() \
            or User.objects.filter(username='admin').first()

        # ── Catalog tối thiểu ────────────────────────────────────────────────
        parts = {}
        for pno, cat, name, price in [
            ('002001', 'tip',     'Tip hàn 0.9mm',     25_000),
            ('001002', 'nozzle',  'Nozzle Ø16',        85_000),
            ('036001', 'tipbody', 'Tip Body M6',       120_000),
            ('045003', 'liner',   'Dây dẫn liner 3m',  350_000),
        ]:
            parts[pno], _ = Part.objects.get_or_create(
                tokin_part_no=pno,
                defaults=dict(category=cat, display_name_vi=name, ecosystem='tokin', price_vnd=price),
            )
            # Cập nhật giá kể cả khi part đã tồn tại (get_or_create không update)
            if parts[pno].price_vnd != price:
                parts[pno].price_vnd = price
                parts[pno].save(update_fields=['price_vnd'])
        torches = {}
        for mc, name in [
            ('TK-508RR',  'Súng hàn robot TK-508RR'),
            ('YMSA-500R', 'Súng hàn robot YMSA-500R'),
            ('WX-500R',   'Súng hàn WX-500R'),
        ]:
            torches[mc], _ = Torch.objects.get_or_create(
                model_code=mc,
                defaults=dict(display_name_vi=name, ecosystem='tokin', current_class='500A'),
            )

        # ── Kho / Zone / Bin ─────────────────────────────────────────────────
        hcm, _ = Warehouse.objects.get_or_create(
            code='HCM', defaults=dict(name='Kho HCM', is_active=True, is_default=True))
        Warehouse.objects.get_or_create(
            code='HN', defaults=dict(name='Kho Hà Nội', is_active=True))

        zone_a, _ = Zone.objects.get_or_create(warehouse=hcm, code='A',
                                               defaults=dict(name='Khu vật tư tiêu hao', purpose='Vật tư tiêu hao'))
        zone_b, _ = Zone.objects.get_or_create(warehouse=hcm, code='B',
                                               defaults=dict(name='Khu súng hàn', purpose='Súng hàn'))

        bins = {}
        bin_specs = [
            (zone_a, 'R01', 'B01'), (zone_a, 'R01', 'B02'), (zone_a, 'R02', 'B01'),
            (zone_b, 'R01', 'B01'), (zone_b, 'R01', 'B02'),
        ]
        for z, rack, bc in bin_specs:
            full = f"HCM-{z.code}-{rack}-{bc}"
            bins[full], _ = Bin.objects.get_or_create(
                zone=z, rack=rack, bin_code=bc,
                defaults=dict(full_code=full, capacity=100))

        # ── Tồn kho (part + torch) ──────────────────────────────────────────
        inv_specs = [
            ('HCM-A-R01-B01', parts['002001'], None, 480, 0, 100),
            ('HCM-A-R01-B02', parts['001002'], None, 60,  0, 50),
            ('HCM-A-R02-B01', parts['036001'], None, 8,   0, 50),   # sắp hết
            ('HCM-A-R02-B01', parts['045003'], None, 5,   0, 20),   # sắp hết
            ('HCM-B-R01-B01', None, torches['TK-508RR'], 6, 1, 3),
            ('HCM-B-R01-B02', None, torches['WX-500R'],  2, 0, 5),  # sắp hết
        ]
        for full, part, torch, onhand, reserved, minlv in inv_specs:
            InventoryItem.objects.get_or_create(
                bin=bins[full], part=part, torch=torch,
                defaults=dict(qty_on_hand=onhand, qty_reserved=reserved, min_level=minlv))

        # ── Serial cho súng hàn ─────────────────────────────────────────────
        dns = Customer.objects.filter(code='KH-0012').first()
        serial_specs = [
            ('TK508RR-0001', torches['TK-508RR'], 'HCM-B-R01-B01', 'in_stock', None),
            ('TK508RR-0002', torches['TK-508RR'], 'HCM-B-R01-B01', 'in_stock', None),
            ('YMSA500R-0007', torches['YMSA-500R'], None, 'sold', dns),
            ('WX500R-0011', torches['WX-500R'], 'HCM-B-R01-B02', 'reserved', None),
        ]
        for serial, torch, binfull, status, cust in serial_specs:
            SerialNumber.objects.get_or_create(
                serial=serial,
                defaults=dict(torch=torch, bin=bins.get(binfull) if binfull else None,
                              status=status, sold_to_customer=cust,
                              received_at=timezone.now(),
                              warranty_until=date.today() + timedelta(days=365)))

        # ── Lot (FEFO) ───────────────────────────────────────────────────────
        Lot.objects.get_or_create(
            lot_no='LOT-2026-001',
            defaults=dict(part=parts['002001'], qty_remaining=480, received_date=date.today(),
                          expires_at=date.today() + timedelta(days=540), bin=bins['HCM-A-R01-B01']))

        # ── ASN ──────────────────────────────────────────────────────────────
        ASN.objects.get_or_create(code='ASN-2026-031',
                                  defaults=dict(warehouse=hcm, supplier='Tokinarc JP',
                                                eta=date.today() + timedelta(days=3)))
        ASN.objects.get_or_create(code='ASN-2026-032',
                                  defaults=dict(warehouse=hcm, supplier='Panasonic VN',
                                                eta=date.today() + timedelta(days=7)))

        # ── Inbound (draft, có line) ────────────────────────────────────────
        inb, created = InboundOrder.objects.get_or_create(
            code='IN-2026-077', defaults=dict(warehouse=hcm, status='draft'))
        if created:
            InboundLine.objects.create(inbound=inb, part=parts['036001'],
                                       qty_expected=100, target_bin=bins['HCM-A-R02-B01'])
            InboundLine.objects.create(inbound=inb, torch=torches['WX-500R'],
                                       qty_expected=20, target_bin=bins['HCM-B-R01-B02'])

        # ── Outbound (picking, có line) ─────────────────────────────────────
        out, created = OutboundOrder.objects.get_or_create(
            code='OUT-2026-112',
            defaults=dict(warehouse=hcm, customer=dns, rule='FIFO', status='picking',
                          sales_order_code='HD-2026-001'))
        if created:
            OutboundLine.objects.create(outbound=out, part=parts['002001'], qty_ordered=50)
            OutboundLine.objects.create(outbound=out, torch=torches['TK-508RR'], qty_ordered=1)

        # ── Stock movements (log mẫu) ───────────────────────────────────────
        if not StockMovement.objects.exists():
            StockMovement.objects.create(warehouse=hcm, part=parts['002001'],
                                         bin=bins['HCM-A-R01-B01'], delta=480,
                                         reason=MovementReason.INBOUND, ref_kind='inbound',
                                         ref_id='IN-2026-070', by_user=user, note='Nhập đầu kỳ')
            StockMovement.objects.create(warehouse=hcm, part=parts['036001'],
                                         bin=bins['HCM-A-R02-B01'], delta=-42,
                                         reason=MovementReason.OUTBOUND, ref_kind='outbound',
                                         ref_id='OUT-2026-100', by_user=user, note='Xuất bán')
            StockMovement.objects.create(warehouse=hcm, torch=torches['TK-508RR'],
                                         bin=bins['HCM-B-R01-B01'], delta=6,
                                         reason=MovementReason.INBOUND, ref_kind='inbound',
                                         ref_id='IN-2026-072', by_user=user, note='Nhập súng')

        self.stdout.write(self.style.SUCCESS(
            f'✅ Seed WMS: {Warehouse.objects.count()} kho, {Bin.objects.count()} bin, '
            f'{InventoryItem.objects.count()} dòng tồn, {SerialNumber.objects.count()} serial, '
            f'{ASN.objects.count()} ASN, {InboundOrder.objects.count()} inbound, '
            f'{OutboundOrder.objects.count()} outbound, {StockMovement.objects.count()} movement.'
        ))
