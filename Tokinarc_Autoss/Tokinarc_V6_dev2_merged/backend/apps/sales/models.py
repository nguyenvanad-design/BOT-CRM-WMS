"""
Tokinarc V6.C — apps/sales/models.py

Gộp đơn bán + hợp đồng khung vào MỘT bảng SalesOrder (V6 gốc Mục 4B.4),
phân biệt bằng order_type. Payment append-only; công nợ derived (total - paid),
KHÔNG có bảng debt riêng (B.2 §5).
"""
from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel, SoftDeleteMixin


class OrderType(models.TextChoices):
    ONE_OFF   = 'one_off',   'Đơn bán'
    FRAMEWORK = 'framework', 'Hợp đồng khung'


class PaymentTerms(models.TextChoices):
    FULL_ON_DELIVERY = 'full_on_delivery', '100% khi giao'
    HALF_ADVANCE     = 'half_advance',     '50% tạm ứng – 50% khi giao'
    NET_30           = 'net_30',           'Công nợ 30 ngày'
    NET_60           = 'net_60',           'Công nợ 60 ngày'


class OrderStatus(models.TextChoices):
    DRAFT     = 'draft',     'Nháp'
    PENDING   = 'pending',   'Chờ ký'
    ACTIVE    = 'active',    'Hiệu lực'
    SHIPPING  = 'shipping',  'Đang giao'
    COMPLETED = 'completed', 'Hoàn tất'
    CANCELLED = 'cancelled', 'Hủy'


class PaymentMethod(models.TextChoices):
    TRANSFER = 'transfer', 'Chuyển khoản'
    CASH     = 'cash',     'Tiền mặt'
    OTHER    = 'other',    'Khác'


class SalesOrder(BaseModel, SoftDeleteMixin):
    code         = models.CharField(max_length=20, unique=True)   # 'HD-2024-045'
    customer     = models.ForeignKey('crm.Customer', on_delete=models.PROTECT, related_name='orders')
    order_type   = models.CharField(max_length=20, choices=OrderType.choices,
                                    default=OrderType.ONE_OFF, db_index=True)
    parent_order = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='child_orders')
    issued_date  = models.DateField()
    valid_from   = models.DateField(null=True, blank=True)
    valid_to     = models.DateField(null=True, blank=True)
    total_vnd    = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    paid_vnd     = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    payment_terms = models.CharField(max_length=20, choices=PaymentTerms.choices,
                                     default=PaymentTerms.FULL_ON_DELIVERY)
    status       = models.CharField(max_length=20, choices=OrderStatus.choices,
                                    default=OrderStatus.DRAFT, db_index=True)
    owner        = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='owned_orders')
    notes        = models.TextField(blank=True)

    class Meta:
        db_table = 'sales_salesorder'
        ordering = ['-issued_date']
        indexes = [models.Index(fields=['customer', 'status', '-issued_date'])]
        constraints = [
            models.CheckConstraint(name='order_paid_le_total',
                                   check=models.Q(paid_vnd__lte=models.F('total_vnd'))),
        ]

    @property
    def debt_amount(self):
        return self.total_vnd - self.paid_vnd

    def __str__(self) -> str:
        return f"{self.code} ({self.get_status_display()})"


class SalesOrderLine(models.Model):
    order        = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='lines')
    part         = models.ForeignKey('catalog.Part', null=True, blank=True,
                                     on_delete=models.PROTECT, db_column='part_no')
    torch        = models.ForeignKey('catalog.Torch', null=True, blank=True,
                                     on_delete=models.PROTECT, db_column='torch_model')
    description  = models.CharField(max_length=200)
    qty          = models.IntegerField()
    unit_price   = models.DecimalField(max_digits=14, decimal_places=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total   = models.DecimalField(max_digits=14, decimal_places=0)
    shipped_qty  = models.IntegerField(default=0)
    order_idx    = models.IntegerField(default=0)

    class Meta:
        db_table = 'sales_salesorderline'
        ordering = ['order_idx']
        constraints = [
            models.CheckConstraint(name='oline_shipped_le_qty',
                                   check=models.Q(shipped_qty__lte=models.F('qty'))),
        ]


class Payment(BaseModel):
    order      = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name='payments')
    amount_vnd = models.DecimalField(max_digits=14, decimal_places=0)
    paid_at    = models.DateField()
    method     = models.CharField(max_length=20, choices=PaymentMethod.choices)
    reference  = models.CharField(max_length=100, blank=True)
    notes      = models.TextField(blank=True)

    class Meta:
        db_table = 'sales_payment'
        ordering = ['-paid_at']
