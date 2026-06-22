"""
Tokinarc V6.C — apps/wms/models.py

App WMS đầy đủ (multi-warehouse từ đầu). Theo đúng pattern apps/crm:
  - BaseModel/SoftDeleteMixin từ apps.common
  - Enum bằng TextChoices
  - FK tới catalog.Part (PK=tokin_part_no) / catalog.Torch (PK=model_code)
  - explicit db_table = 'wms_*'

Cấu trúc kho: Warehouse → Zone → Bin. Tồn (InventoryItem) gắn vào Bin,
warehouse suy ra qua bin.zone.warehouse. Serial cho torch (truy xuất từng cái),
Lot cho part theo FEFO. Mọi biến động ghi StockMovement (append-only domain log).

LƯU Ý multi-warehouse (quyết định B.0 #7):
  - Schema hỗ trợ nhiều kho ngay từ đầu.
  - API luôn nhận/lọc theo warehouse — KHÔNG hardcode HCM (xem views.py).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel, SoftDeleteMixin


# ─── Enums ───────────────────────────────────────────────────────────────────
class SerialStatus(models.TextChoices):
    IN_STOCK = 'in_stock', 'Trong kho'
    RESERVED = 'reserved', 'Đã giữ'
    SHIPPED  = 'shipped',  'Đã giao'
    SOLD     = 'sold',     'Đã bán'
    RETURNED = 'returned', 'Trả lại'
    SCRAPPED = 'scrapped', 'Hủy'


class MovementReason(models.TextChoices):
    INBOUND  = 'inbound',  'Nhập kho'
    OUTBOUND = 'outbound', 'Xuất kho'
    ADJUST   = 'adjust',   'Điều chỉnh'
    TRANSFER = 'transfer', 'Chuyển kho'
    RETURN   = 'return',   'Trả hàng'


class OutboundRule(models.TextChoices):
    FIFO    = 'FIFO',    'Nhập trước xuất trước'
    FEFO    = 'FEFO',    'Hết hạn trước xuất trước'
    NEAREST = 'NEAREST', 'Gần cửa xuất nhất'


class InboundStatus(models.TextChoices):
    DRAFT     = 'draft',     'Nháp'
    CONFIRMED = 'confirmed', 'Đã xác nhận'
    PUTAWAY   = 'putaway',   'Đã cất kho'
    CANCELLED = 'cancelled', 'Hủy'


class OutboundStatus(models.TextChoices):
    DRAFT     = 'draft',     'Nháp'
    PICKING   = 'picking',   'Đang soạn'
    PICKED    = 'picked',    'Đã soạn xong'
    SHIPPED   = 'shipped',   'Đã giao'
    CANCELLED = 'cancelled', 'Hủy'


# ─── Cấu trúc kho ────────────────────────────────────────────────────────────
class Warehouse(BaseModel):
    """Kho vật lý. HCM là kho mặc định; thêm kho mới không cần đổi schema."""
    code      = models.CharField(max_length=10, unique=True)   # 'HCM','HN','DN'
    name      = models.CharField(max_length=100)
    address   = models.JSONField(default=dict, blank=True)     # {street,district,city}
    is_active = models.BooleanField(default=True, db_index=True)
    is_default = models.BooleanField(default=False)            # kho auto khi FE chỉ 1 kho

    class Meta:
        db_table = 'wms_warehouse'
        ordering = ['code']

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Zone(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='zones')
    code      = models.CharField(max_length=10)
    name      = models.CharField(max_length=100)
    purpose   = models.CharField(max_length=100, blank=True)   # 'Vật tư tiêu hao','Súng hàn'

    class Meta:
        db_table = 'wms_zone'
        ordering = ['warehouse', 'code']
        constraints = [
            models.UniqueConstraint(fields=['warehouse', 'code'], name='uniq_zone_per_wh'),
        ]

    def __str__(self) -> str:
        return f"{self.warehouse.code}/{self.code}"


class Bin(models.Model):
    zone      = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='bins')
    rack      = models.CharField(max_length=10)
    bin_code  = models.CharField(max_length=10)
    full_code = models.CharField(max_length=30, unique=True, db_index=True)  # 'HCM-A-R01-B03'
    capacity  = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'wms_bin'
        ordering = ['full_code']
        constraints = [
            models.UniqueConstraint(fields=['zone', 'rack', 'bin_code'], name='uniq_bin_in_zone'),
        ]

    def __str__(self) -> str:
        return self.full_code


# ─── Tồn kho ─────────────────────────────────────────────────────────────────
class InventoryItem(models.Model):
    """
    Tồn theo (bin, part) HOẶC (bin, torch) — đúng MỘT trong hai not-null.
    Warehouse suy ra qua bin.zone.warehouse.
    """
    bin         = models.ForeignKey(Bin, on_delete=models.PROTECT, related_name='items')
    part        = models.ForeignKey('catalog.Part', null=True, blank=True,
                                    on_delete=models.PROTECT, related_name='inventory',
                                    db_column='part_no')
    torch       = models.ForeignKey('catalog.Torch', null=True, blank=True,
                                    on_delete=models.PROTECT, related_name='inventory',
                                    db_column='torch_model')
    qty_on_hand  = models.IntegerField(default=0)
    qty_reserved = models.IntegerField(default=0)
    min_level    = models.IntegerField(default=0)
    received_at  = models.DateTimeField(null=True, blank=True, db_index=True)  # FIFO: lần nhập đầu
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wms_inventory_item'
        ordering = ['bin__full_code']
        constraints = [
            models.UniqueConstraint(fields=['bin', 'part'], name='uniq_bin_part',
                                    condition=models.Q(part__isnull=False)),
            models.UniqueConstraint(fields=['bin', 'torch'], name='uniq_bin_torch',
                                    condition=models.Q(torch__isnull=False)),
            # Đúng MỘT trong hai (part XOR torch) not-null
            models.CheckConstraint(
                name='inv_part_xor_torch',
                check=(models.Q(part__isnull=False, torch__isnull=True) |
                       models.Q(part__isnull=True,  torch__isnull=False)),
            ),
            models.CheckConstraint(name='inv_qty_nonneg', check=models.Q(qty_on_hand__gte=0)),
            models.CheckConstraint(name='inv_reserved_nonneg', check=models.Q(qty_reserved__gte=0)),
            models.CheckConstraint(name='inv_reserved_le_onhand',
                                   check=models.Q(qty_reserved__lte=models.F('qty_on_hand'))),
        ]
        indexes = [
            models.Index(fields=['part'], name='inv_part_idx'),
            models.Index(fields=['torch'], name='inv_torch_idx'),
            # query "sắp hết": qty_on_hand <= min_level (partial index trong migration)
        ]

    @property
    def available_qty(self) -> int:
        """Tồn khả dụng. LƯU Ý: viewset annotate alias 'qty_available' cho API —
        không đặt property tên 'qty_available' để tránh xung đột annotation setter."""
        return self.qty_on_hand - self.qty_reserved

    def __str__(self) -> str:
        what = self.part_id or self.torch_id
        return f"{what} @ {self.bin.full_code}: {self.qty_on_hand}"


class SerialNumber(BaseModel, SoftDeleteMixin):
    """Mỗi súng hàn 1 serial — truy xuất từng cái + bảo hành."""
    serial = models.CharField(max_length=40, unique=True, db_index=True)
    torch  = models.ForeignKey('catalog.Torch', on_delete=models.PROTECT,
                               related_name='serials', db_column='torch_model')
    bin    = models.ForeignKey(Bin, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='serials')
    status = models.CharField(max_length=20, choices=SerialStatus.choices,
                              default=SerialStatus.IN_STOCK, db_index=True)
    sold_to_customer = models.ForeignKey('crm.Customer', null=True, blank=True,
                                         on_delete=models.PROTECT, related_name='owned_serials')
    sold_order       = models.CharField(max_length=20, blank=True)  # SalesOrder.code (sales chưa có app)
    received_at      = models.DateTimeField(null=True, blank=True)
    warranty_until   = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'wms_serial'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'torch'])]

    def __str__(self) -> str:
        return f"{self.serial} ({self.torch_id})"


class Lot(models.Model):
    """Lô part theo hạn dùng — FEFO."""
    lot_no        = models.CharField(max_length=40, unique=True, db_index=True)
    part          = models.ForeignKey('catalog.Part', on_delete=models.PROTECT,
                                      related_name='lots', db_column='part_no')
    qty_remaining = models.IntegerField()
    received_date = models.DateField()
    expires_at    = models.DateField(null=True, blank=True, db_index=True)
    bin           = models.ForeignKey(Bin, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = 'wms_lot'
        ordering = ['expires_at', 'received_date']

    def __str__(self) -> str:
        return f"{self.lot_no} ({self.part_id})"


# ─── Nhập kho (ASN → Inbound) ────────────────────────────────────────────────
class ASN(BaseModel):
    """Advance Shipment Notice — báo trước hàng về."""
    code        = models.CharField(max_length=20, unique=True)   # 'ASN-2026-031'
    warehouse   = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='asns')
    supplier    = models.CharField(max_length=200, blank=True)
    eta         = models.DateField(null=True, blank=True)
    is_arrived  = models.BooleanField(default=False, db_index=True)
    notes       = models.TextField(blank=True)

    class Meta:
        db_table = 'wms_asn'
        ordering = ['-created_at']


class InboundOrder(BaseModel):
    code      = models.CharField(max_length=20, unique=True)     # 'IN-2026-077'
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='inbounds')
    asn       = models.ForeignKey(ASN, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='inbound_orders')
    status    = models.CharField(max_length=20, choices=InboundStatus.choices,
                                 default=InboundStatus.DRAFT, db_index=True)
    received_at = models.DateTimeField(null=True, blank=True)
    notes     = models.TextField(blank=True)

    class Meta:
        db_table = 'wms_inbound_order'
        ordering = ['-created_at']


class InboundLine(models.Model):
    inbound     = models.ForeignKey(InboundOrder, on_delete=models.CASCADE, related_name='lines')
    part        = models.ForeignKey('catalog.Part', null=True, blank=True,
                                    on_delete=models.PROTECT, db_column='part_no')
    torch       = models.ForeignKey('catalog.Torch', null=True, blank=True,
                                    on_delete=models.PROTECT, db_column='torch_model')
    qty_expected = models.IntegerField()
    qty_received = models.IntegerField(default=0)
    target_bin   = models.ForeignKey(Bin, null=True, blank=True, on_delete=models.SET_NULL)
    lot_no       = models.CharField(max_length=40, blank=True)
    lot_expires  = models.DateField(null=True, blank=True)   # hạn dùng của lô (nếu có)
    order_idx    = models.IntegerField(default=0)

    class Meta:
        db_table = 'wms_inbound_line'
        ordering = ['order_idx']
        constraints = [
            models.CheckConstraint(
                name='inbound_part_xor_torch',
                check=(models.Q(part__isnull=False, torch__isnull=True) |
                       models.Q(part__isnull=True,  torch__isnull=False))),
            models.CheckConstraint(name='inbound_received_le_expected',
                                   check=models.Q(qty_received__lte=models.F('qty_expected'))),
        ]


# ─── Xuất kho (Outbound → PickList) ──────────────────────────────────────────
class OutboundOrder(BaseModel):
    code       = models.CharField(max_length=20, unique=True)    # 'OUT-2026-112'
    warehouse  = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='outbounds')
    sales_order_code = models.CharField(max_length=20, blank=True)  # link SalesOrder (sales chưa có)
    customer   = models.ForeignKey('crm.Customer', null=True, blank=True,
                                   on_delete=models.PROTECT, related_name='outbounds')
    rule       = models.CharField(max_length=10, choices=OutboundRule.choices,
                                  default=OutboundRule.FIFO)
    status     = models.CharField(max_length=20, choices=OutboundStatus.choices,
                                  default=OutboundStatus.DRAFT, db_index=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    notes      = models.TextField(blank=True)

    class Meta:
        db_table = 'wms_outbound_order'
        ordering = ['-created_at']


class OutboundLine(models.Model):
    outbound    = models.ForeignKey(OutboundOrder, on_delete=models.CASCADE, related_name='lines')
    part        = models.ForeignKey('catalog.Part', null=True, blank=True,
                                    on_delete=models.PROTECT, db_column='part_no')
    torch       = models.ForeignKey('catalog.Torch', null=True, blank=True,
                                    on_delete=models.PROTECT, db_column='torch_model')
    qty_ordered = models.IntegerField()
    qty_picked  = models.IntegerField(default=0)
    order_idx   = models.IntegerField(default=0)

    class Meta:
        db_table = 'wms_outbound_line'
        ordering = ['order_idx']
        constraints = [
            models.CheckConstraint(
                name='outbound_part_xor_torch',
                check=(models.Q(part__isnull=False, torch__isnull=True) |
                       models.Q(part__isnull=True,  torch__isnull=False))),
            models.CheckConstraint(name='outbound_picked_le_ordered',
                                   check=models.Q(qty_picked__lte=models.F('qty_ordered'))),
        ]


class PickListItem(models.Model):
    """Dòng soạn hàng — bin cụ thể được phân để pick (theo rule FIFO/FEFO/NEAREST)."""
    outbound_line = models.ForeignKey(OutboundLine, on_delete=models.CASCADE, related_name='picks')
    bin           = models.ForeignKey(Bin, on_delete=models.PROTECT)
    lot           = models.ForeignKey(Lot, null=True, blank=True, on_delete=models.SET_NULL)
    serial        = models.ForeignKey(SerialNumber, null=True, blank=True, on_delete=models.SET_NULL)
    qty           = models.IntegerField()
    is_picked     = models.BooleanField(default=False)

    class Meta:
        db_table = 'wms_pick_list_item'


# ─── Stock movement (append-only domain log) ─────────────────────────────────
class StockMovement(models.Model):
    """
    Append-only. Mọi thay đổi tồn ghi 1 dòng. Đây là domain log của kho
    (khác AuditLog generic — không log đúp).
    """
    id       = models.BigAutoField(primary_key=True)
    ts       = models.DateTimeField(auto_now_add=True, db_index=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='movements')
    part     = models.ForeignKey('catalog.Part', null=True, blank=True,
                                 on_delete=models.PROTECT, db_column='part_no')
    torch    = models.ForeignKey('catalog.Torch', null=True, blank=True,
                                 on_delete=models.PROTECT, db_column='torch_model')
    bin      = models.ForeignKey(Bin, on_delete=models.PROTECT)
    delta    = models.IntegerField()                 # +nhập / -xuất
    reason   = models.CharField(max_length=20, choices=MovementReason.choices, db_index=True)
    ref_kind = models.CharField(max_length=20, blank=True)   # inbound/outbound/adjust
    ref_id   = models.CharField(max_length=40, blank=True)
    by_user  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.PROTECT)
    note     = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'wms_stock_movement'
        ordering = ['-ts']
        indexes = [
            models.Index(fields=['part', '-ts'], name='mov_part_idx'),
            models.Index(fields=['bin', '-ts'], name='mov_bin_idx'),
            models.Index(fields=['warehouse', '-ts'], name='mov_wh_idx'),
        ]

    def __str__(self) -> str:
        what = self.part_id or self.torch_id
        return f"[{self.ts:%Y-%m-%d}] {what} {self.delta:+d} ({self.reason})"


# ─── Kiểm kê (cycle count) ───────────────────────────────────────────────────
class CycleCountStatus(models.TextChoices):
    OPEN      = 'open',      'Đang đếm'
    APPLIED   = 'applied',   'Đã áp dụng'
    CANCELLED = 'cancelled', 'Hủy'


class CycleCount(BaseModel):
    """Phiên kiểm kê kho. Quét đếm thực tế → áp dụng để điều chỉnh tồn."""
    code      = models.CharField(max_length=20, unique=True)   # 'KK-2026-001'
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='cycle_counts')
    status    = models.CharField(max_length=20, choices=CycleCountStatus.choices,
                                 default=CycleCountStatus.OPEN, db_index=True)
    note      = models.CharField(max_length=200, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'wms_cycle_count'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.code} ({self.warehouse_id})"


class CycleCountLine(models.Model):
    """1 dòng đếm: ô × mặt hàng, tồn hệ thống lúc quét vs số đếm thực tế."""
    session     = models.ForeignKey(CycleCount, on_delete=models.CASCADE, related_name='lines')
    bin         = models.ForeignKey(Bin, on_delete=models.PROTECT)
    part        = models.ForeignKey('catalog.Part', null=True, blank=True,
                                    on_delete=models.PROTECT, db_column='part_no')
    torch       = models.ForeignKey('catalog.Torch', null=True, blank=True,
                                    on_delete=models.PROTECT, db_column='torch_model')
    system_qty  = models.IntegerField(default=0)   # tồn hệ thống lúc quét
    counted_qty = models.IntegerField(default=0)   # số đếm thực tế
    counted_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wms_cycle_count_line'
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['session', 'bin', 'part', 'torch'],
                                    name='uniq_cc_line'),
        ]

    @property
    def diff(self) -> int:
        return self.counted_qty - self.system_qty
