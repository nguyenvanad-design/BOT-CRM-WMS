"""
Tokinarc — apps/purchasing/models.py
Mua hàng (Purchase-to-Pay): Nhà cung cấp + Đơn mua + Công nợ phải trả (AP).
Nhận hàng theo PO sẽ cộng tồn qua wms.services.receive_stock.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel, SoftDeleteMixin


class Supplier(BaseModel, SoftDeleteMixin):
    code      = models.CharField(max_length=20, unique=True)   # 'NCC-0001'
    name      = models.CharField(max_length=200, db_index=True)
    tax_code  = models.CharField(max_length=20, blank=True)
    phone     = models.CharField(max_length=30, blank=True)
    email     = models.EmailField(blank=True)
    address   = models.CharField(max_length=255, blank=True)
    notes     = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = 'pur_supplier'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class PurchaseStatus(models.TextChoices):
    DRAFT       = 'draft',       'Nháp'            # đề xuất — chờ duyệt cấp 1
    PENDING_CEO = 'pending_ceo', 'Chờ CEO duyệt'   # qua cấp 1, vượt ngưỡng
    APPROVED    = 'approved',    'Đã duyệt'        # duyệt xong — chờ đặt hàng
    REJECTED    = 'rejected',    'Từ chối'
    ORDERED     = 'ordered',     'Đã đặt'
    PARTIAL     = 'partial',     'Nhận một phần'
    RECEIVED    = 'received',    'Đã nhận đủ'
    CANCELLED   = 'cancelled',   'Hủy'


class PurchaseOrder(BaseModel, SoftDeleteMixin):
    code        = models.CharField(max_length=20, unique=True)   # 'PO-2026-001'
    supplier    = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='orders')
    warehouse   = models.ForeignKey('wms.Warehouse', on_delete=models.PROTECT,
                                    related_name='purchase_orders')
    status      = models.CharField(max_length=20, choices=PurchaseStatus.choices,
                                   default=PurchaseStatus.DRAFT, db_index=True)
    order_date  = models.DateField(null=True, blank=True)
    expected_date = models.DateField(null=True, blank=True)
    total_vnd   = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    paid_vnd    = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    owner       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name='purchase_orders')
    notes       = models.TextField(blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    # Duyệt 2 cấp (giống Báo giá): cấp 1 = manager, cấp 2 = CEO (vượt ngưỡng).
    l1_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='l1_approved_pos')
    l1_approved_at = models.DateTimeField(null=True, blank=True)
    l2_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='l2_approved_pos')
    l2_approved_at = models.DateTimeField(null=True, blank=True)
    approved_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='approved_pos')

    class Meta:
        db_table = 'pur_order'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'supplier'])]

    def __str__(self) -> str:
        return f"{self.code} — {self.supplier.name}"

    @property
    def debt_vnd(self):
        return (self.total_vnd or 0) - (self.paid_vnd or 0)

    def recompute_total(self):
        agg = self.lines.aggregate(s=models.Sum('line_total'))
        self.total_vnd = agg['s'] or 0

    def requires_l2(self) -> bool:
        """Đơn mua ≥ ngưỡng PO_L2_THRESHOLD_VND cần duyệt cấp 2 (CEO)."""
        from django.conf import settings as dj_settings
        threshold = getattr(dj_settings, 'PO_L2_THRESHOLD_VND', 100_000_000)
        return (self.total_vnd or 0) >= threshold


class PurchaseOrderLine(models.Model):
    po          = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
    part        = models.ForeignKey('catalog.Part', on_delete=models.PROTECT, db_column='part_no')
    description = models.CharField(max_length=200, blank=True)
    qty         = models.IntegerField()
    unit_cost   = models.DecimalField(max_digits=14, decimal_places=0)
    line_total  = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    qty_received = models.IntegerField(default=0)
    target_bin  = models.ForeignKey('wms.Bin', null=True, blank=True, on_delete=models.SET_NULL)
    order_idx   = models.IntegerField(default=0)

    class Meta:
        db_table = 'pur_order_line'
        ordering = ['order_idx']
        constraints = [
            models.CheckConstraint(name='po_received_le_qty',
                                   check=models.Q(qty_received__lte=models.F('qty'))),
        ]


class PurchasePayment(BaseModel):
    """Công nợ phải trả NCC — mỗi lần trả 1 dòng."""
    po         = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name='payments')
    amount_vnd = models.DecimalField(max_digits=15, decimal_places=0)
    paid_at    = models.DateField()
    method     = models.CharField(max_length=20, default='transfer')
    reference  = models.CharField(max_length=100, blank=True)
    notes      = models.TextField(blank=True)

    class Meta:
        db_table = 'pur_payment'
        ordering = ['-paid_at']
