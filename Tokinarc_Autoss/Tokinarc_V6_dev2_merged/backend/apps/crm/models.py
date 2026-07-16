"""
Tokinarc V6.C — apps/crm/models.py

App mẫu end-to-end: Customer + Contact.
Demo các pattern dùng xuyên suốt hệ thống:
  - BaseModel + SoftDeleteMixin từ apps.common
  - Enum bằng TextChoices (debug dễ hơn IntegerChoices)
  - Ownership: customer thuộc 1 sale (User)
  - Nested entity: Contact thuộc Customer
  - JSONField cho address (chi tiết linh hoạt mà ít query)
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel, SoftDeleteMixin


class CustomerSegment(models.TextChoices):
    FACTORY    = 'factory',    'Nhà máy SX'
    INTEGRATOR = 'integrator', 'Robot Integrator'
    DEALER     = 'dealer',     'Đại lý'
    OEM        = 'oem',        'OEM'
    SHIPYARD   = 'shipyard',   'Đóng tàu'
    OTHER      = 'other',      'Khác'


class CustomerStatus(models.TextChoices):
    NEW       = 'new',       'Mới'
    POTENTIAL = 'potential', 'Tiềm năng'
    VIP       = 'vip',       'VIP'
    NORMAL    = 'normal',    'Bình thường'
    INACTIVE  = 'inactive',  'Không hoạt động'


class PriceTier(models.Model):
    """Bảng giá theo PHÂN KHÚC khách (segment). Giá đề xuất = giá niêm yết × (1 − discount%).
    Chỉ GỢI Ý cho sale (vẫn sửa tay được) → giá nhất quán + báo giá nhanh."""
    segment      = models.CharField(max_length=20, choices=CustomerSegment.choices, unique=True)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # % giảm so với giá niêm yết
    label        = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = 'crm_price_tier'
        ordering = ['segment']

    def __str__(self) -> str:
        return f"{self.segment}: -{self.discount_pct}%"


class ContactChannel(models.TextChoices):
    ZALO  = 'zalo',  'Zalo'
    PHONE = 'phone', 'Điện thoại'
    EMAIL = 'email', 'Email'
    OTHER = 'other', 'Khác'


class Customer(BaseModel, SoftDeleteMixin):
    """KH chính — mỗi KH thuộc 1 sale (owner)."""
    code      = models.CharField(max_length=20, unique=True)   # 'KH-0012'
    name      = models.CharField(max_length=200, db_index=True)
    tax_code  = models.CharField(max_length=20, blank=True, db_index=True)
    segment   = models.CharField(
        max_length=20, choices=CustomerSegment.choices,
        default=CustomerSegment.OTHER, db_index=True,
    )
    region    = models.CharField(max_length=30, blank=True, db_index=True)
    address   = models.JSONField(default=dict, blank=True)   # {street, district, city, gps_lat, gps_lng}
    status    = models.CharField(
        max_length=20, choices=CustomerStatus.choices,
        default=CustomerStatus.NEW, db_index=True,
    )
    owner     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='owned_customers',
    )
    credit_limit_vnd = models.DecimalField(max_digits=15, decimal_places=0, default=0)  # 0 = không giới hạn
    notes     = models.TextField(blank=True)

    class Meta:
        db_table = 'crm_customer'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['segment', 'status']),
            models.Index(fields=['owner', '-created_at']),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Contact(BaseModel):
    """Người liên hệ thuộc KH."""
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='contacts',
    )
    full_name = models.CharField(max_length=100)
    title     = models.CharField(max_length=50, blank=True)   # 'Giám đốc nhà máy'
    phone     = models.CharField(max_length=20, blank=True)
    email     = models.EmailField(blank=True)
    preferred_channel = models.CharField(
        max_length=20, choices=ContactChannel.choices, default=ContactChannel.ZALO,
    )
    is_primary = models.BooleanField(default=False)
    notes      = models.TextField(blank=True)

    class Meta:
        db_table = 'crm_contact'
        ordering = ['-is_primary', 'full_name']
        constraints = [
            # Mỗi KH chỉ 1 primary contact
            models.UniqueConstraint(
                fields=['customer'], condition=models.Q(is_primary=True),
                name='uniq_customer_primary_contact',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.customer.code})"


# ════════════════════════════════════════════════════════════════════════
# V6.C-fix3 — CRM mở rộng: Lead, Opportunity, Quote, Visit, Ticket
# Kích hoạt 6 write tool trong chatbot/tool_clients.py (trước đó 404).
# Pattern: BaseModel + SoftDeleteMixin, TextChoices, FK Customer/User.
# ════════════════════════════════════════════════════════════════════════

class LeadStatus(models.TextChoices):
    NEW         = 'new',         'Mới'
    CONTACTED   = 'contacted',   'Đã liên hệ'
    QUALIFIED   = 'qualified',   'Đủ điều kiện'
    CONVERTED   = 'converted',   'Đã chuyển'
    LOST        = 'lost',        'Thất bại'


class LeadSource(models.TextChoices):
    """Nguồn lead — chuẩn hóa để thống kê kênh. Giữ các giá trị máy cũ
    (chatbot_khach/chatbot/manual/zalo) để không vỡ dữ liệu sẵn có."""
    EXHIBITION  = 'exhibition',    'Triển lãm / Hội chợ'
    REFERRAL    = 'referral',      'Giới thiệu'
    WEBSITE_BOT = 'chatbot_khach', 'Website / Bot khách'
    ASSISTANT   = 'chatbot',       'Trợ lý nội bộ'
    ZALO        = 'zalo',          'Zalo'
    FACEBOOK    = 'facebook_ads',  'Facebook Ads'
    GOOGLE      = 'google_ads',    'Google Ads'
    TELESALES   = 'telesales',     'Telesales'
    DEALER      = 'dealer',        'Đại lý / NPP'
    MANUAL      = 'manual',        'Nhập tay'
    OTHER       = 'other',         'Khác'


class Lead(BaseModel, SoftDeleteMixin):
    """Khách hàng tiềm năng chưa thành Customer."""
    name      = models.CharField(max_length=200, db_index=True)
    company   = models.CharField(max_length=200, blank=True)
    phone     = models.CharField(max_length=20, blank=True, db_index=True)
    email     = models.EmailField(blank=True)
    source    = models.CharField(max_length=40, blank=True, db_index=True)  # LeadSource
    campaign  = models.CharField(max_length=80, blank=True)   # chiến dịch QC cụ thể
    referred_by = models.CharField(max_length=120, blank=True, db_index=True)  # người giới thiệu
    status    = models.CharField(
        max_length=20, choices=LeadStatus.choices,
        default=LeadStatus.NEW, db_index=True,
    )
    score     = models.IntegerField(default=0)   # AI lead scoring 0-100
    owner     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='owned_leads',
    )
    # Khi convert → trỏ tới Customer được tạo (loose link, nullable)
    converted_customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='from_leads',
    )
    # Nhu cầu: sản phẩm quan tâm + số lượng → tự tính giá trị deal (đổ về Opportunity)
    interest_part = models.ForeignKey(
        'catalog.Part', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    interest_qty  = models.PositiveIntegerField(default=0)
    notes     = models.TextField(blank=True)

    class Meta:
        db_table = 'crm_lead'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['status', '-score'], name='crm_lead_status_score_idx'),
            models.Index(fields=['owner', '-created_at'], name='crm_lead_owner_idx'),
        ]

    def __str__(self) -> str:
        return f"Lead: {self.name}"


class OppStage(models.TextChoices):
    PROSPECT    = 'prospect',    'Tiềm năng'
    QUALIFY     = 'qualify',     'Thẩm định'
    PROPOSAL    = 'proposal',    'Đề xuất'
    NEGOTIATE   = 'negotiate',   'Đàm phán'
    WON         = 'won',         'Thắng'
    LOST        = 'lost',        'Thua'


class OppLostReason(models.TextChoices):
    """Lý do THUA deal — bắt buộc chọn khi đánh dấu thua (phân tích win/loss)."""
    PRICE      = 'price',      'Giá cao'
    COMPETITOR = 'competitor', 'Chọn đối thủ'
    BUDGET     = 'budget',     'Hết ngân sách / hoãn dự án'
    NO_NEED    = 'no_need',    'Hết nhu cầu'
    NO_CONTACT = 'no_contact', 'Mất liên lạc'
    OTHER      = 'other',      'Khác'


class Opportunity(BaseModel, SoftDeleteMixin):
    """Cơ hội bán hàng gắn với 1 Customer."""
    customer  = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='opportunities',
    )
    title     = models.CharField(max_length=200)
    stage     = models.CharField(
        max_length=20, choices=OppStage.choices,
        default=OppStage.PROSPECT, db_index=True,
    )
    est_value_vnd = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    probability   = models.IntegerField(default=0)   # 0-100 %
    expected_close = models.DateField(null=True, blank=True)
    owner     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='owned_opportunities',
    )
    notes     = models.TextField(blank=True)
    # Win/loss: lý do thua (bắt buộc khi mark-lost) + ghi chú thêm của sale.
    lost_reason = models.CharField(max_length=20, choices=OppLostReason.choices,
                                   blank=True, default='')
    lost_note   = models.TextField(blank=True)

    class Meta:
        db_table = 'crm_opportunity'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['stage', 'customer'], name='crm_opp_stage_cust_idx'),
            models.Index(fields=['owner', '-created_at'], name='crm_opp_owner_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_stage_display()})"


class QuoteStatus(models.TextChoices):
    DRAFT       = 'draft',       'Nháp'
    SENT        = 'sent',        'Đã gửi'
    PENDING_CEO = 'pending_ceo', 'Chờ CEO duyệt'   # đã qua cấp 1, chờ cấp 2
    APPROVED    = 'approved',    'Đã duyệt'
    REJECTED    = 'rejected',    'Từ chối'
    CONVERTED   = 'converted',   'Đã chuyển hợp đồng'
    EXPIRED     = 'expired',     'Hết hạn'


class Quote(BaseModel, SoftDeleteMixin):
    """Báo giá. total_vnd tính từ lines ở server, KHÔNG tin client."""
    code      = models.CharField(max_length=20, unique=True)   # 'BG-0042'
    customer  = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='quotes',
    )
    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quotes',
    )
    status    = models.CharField(
        max_length=20, choices=QuoteStatus.choices,
        default=QuoteStatus.DRAFT, db_index=True,
    )
    due_date  = models.DateField(null=True, blank=True)   # ngày dự kiến chốt
    valid_until = models.DateField(null=True, blank=True)  # hạn hiệu lực giá báo
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # % chiết khấu cả báo giá
    # Điều khoản thanh toán sale thỏa thuận với khách (tự do) — cấp duyệt thấy, đổ về đơn.
    # VD: "30% khi giao, 70% sau 30 ngày" / "50% khi nhận, còn lại sau 45 ngày".
    payment_terms_note = models.TextField(blank=True)
    total_vnd = models.DecimalField(max_digits=15, decimal_places=0, default=0)    # = tạm tính × (1 − ck%)
    owner     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='owned_quotes',
    )
    # approved_by = người duyệt cuối cùng (cấp 1 nếu dưới ngưỡng, cấp 2 nếu vượt)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_quotes',
    )
    # Duyệt 2 cấp: cấp 1 (manager) → cấp 2 (CEO, chỉ khi total_vnd ≥ ngưỡng)
    l1_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='l1_approved_quotes',
    )
    l1_approved_at = models.DateTimeField(null=True, blank=True)
    l2_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='l2_approved_quotes',
    )
    l2_approved_at = models.DateTimeField(null=True, blank=True)
    # Loose link sang sales.SalesOrder khi to-contract (tránh circular import)
    contract_order_code = models.CharField(max_length=30, blank=True, db_index=True)
    notes     = models.TextField(blank=True)

    class Meta:
        db_table = 'crm_quote'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['status', 'customer'], name='crm_quote_status_cust_idx'),
            models.Index(fields=['owner', '-created_at'], name='crm_quote_owner_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.customer.name}"

    @property
    def subtotal_vnd(self):
        """Tạm tính = tổng dòng (trước chiết khấu)."""
        agg = self.lines.aggregate(s=models.Sum(models.F('qty') * models.F('unit_price_vnd')))
        return agg['s'] or 0

    def recompute_total(self) -> None:
        """Tổng = tạm tính × (1 − chiết khấu%). Gọi sau khi thêm/sửa line/ck."""
        sub = self.subtotal_vnd
        self.total_vnd = int(round(float(sub) * (1 - float(self.discount_pct or 0) / 100)))

    def within_sale_authority(self) -> bool:
        """Chiết khấu ≤ hạn mức sale → không cần duyệt (tự duyệt)."""
        return float(self.discount_pct or 0) <= getattr(settings, 'DISCOUNT_SALE_MAX_PCT', 5)

    def requires_l2(self) -> bool:
        """Chiết khấu > hạn mức manager → cần CEO duyệt (cấp 2)."""
        return float(self.discount_pct or 0) > getattr(settings, 'DISCOUNT_MANAGER_MAX_PCT', 10)


class QuoteLine(models.Model):
    """Dòng báo giá. part_no là loose key sang catalog (PK string)."""
    quote     = models.ForeignKey(
        Quote, on_delete=models.CASCADE, related_name='lines',
    )
    part_no   = models.CharField(max_length=40, db_index=True)
    part_name = models.CharField(max_length=200, blank=True)   # snapshot tên lúc báo giá
    qty       = models.IntegerField(default=1)
    unit_price_vnd = models.DecimalField(max_digits=13, decimal_places=0, default=0)

    class Meta:
        db_table = 'crm_quote_line'
        ordering = ['id']

    def __str__(self) -> str:
        return f"{self.part_no} x{self.qty}"


class Visit(BaseModel):
    """Báo cáo viếng thăm khách hàng (Visit Report)."""
    customer  = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='visits',
    )
    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='visits',
    )
    visit_date = models.DateField(db_index=True)
    purpose    = models.CharField(max_length=200)
    summary    = models.TextField(blank=True)
    next_action = models.CharField(max_length=200, blank=True)
    gps        = models.JSONField(default=dict, blank=True)   # {lat, lng} check-in
    # Ghi âm buổi gặp + recap (sau khi sale đi họp về)
    recording  = models.ForeignKey(
        'storage.FileObject', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',   # file ghi âm (audio)
    )
    recap_file = models.ForeignKey(
        'storage.FileObject', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',   # file recap (Word/PDF)
    )
    recap_text = models.TextField(blank=True)   # văn bản recap từ ghi âm
    owner      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='visits',
    )

    class Meta:
        db_table = 'crm_visit'
        ordering = ['-visit_date']
        indexes  = [
            models.Index(fields=['customer', '-visit_date'], name='crm_visit_cust_idx'),
            models.Index(fields=['owner', '-visit_date'], name='crm_visit_owner_idx'),
        ]

    def __str__(self) -> str:
        return f"Visit {self.customer.code} @ {self.visit_date}"


class TicketStatus(models.TextChoices):
    OPEN        = 'open',        'Mở'
    IN_PROGRESS = 'in_progress', 'Đang xử lý'
    RESOLVED    = 'resolved',    'Đã giải quyết'
    CLOSED      = 'closed',      'Đóng'


class TicketPriority(models.TextChoices):
    LOW    = 'low',    'Thấp'
    MEDIUM = 'medium', 'Trung bình'
    HIGH   = 'high',   'Cao'
    URGENT = 'urgent', 'Khẩn'


class Ticket(BaseModel, SoftDeleteMixin):
    """Service Ticket — yêu cầu hỗ trợ/bảo hành từ khách."""
    code      = models.CharField(max_length=20, unique=True)   # 'TK-0108'
    customer  = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='tickets',
    )
    title     = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status    = models.CharField(
        max_length=20, choices=TicketStatus.choices,
        default=TicketStatus.OPEN, db_index=True,
    )
    priority  = models.CharField(
        max_length=20, choices=TicketPriority.choices,
        default=TicketPriority.MEDIUM, db_index=True,
    )
    # Loose key sang wms serial (sản phẩm bị lỗi), nullable
    serial_no = models.CharField(max_length=60, blank=True, db_index=True)
    assignee  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_tickets',
    )
    created_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_tickets',
    )
    resolution = models.TextField(blank=True)   # cách xử lý / kết quả khắc phục của kỹ sư
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'crm_ticket'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['status', 'priority'], name='crm_ticket_status_prio_idx'),
            models.Index(fields=['customer', '-created_at'], name='crm_ticket_cust_idx'),
            models.Index(fields=['assignee', 'status'], name='crm_ticket_assignee_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.title}"


# ════════════════════════════════════════════════════════════════════════
# Hợp đồng (Contract) + Hoạt động (Activity)
# ════════════════════════════════════════════════════════════════════════

class ContractStatus(models.TextChoices):
    DRAFT       = 'draft',        'Nháp'            # soạn — chờ duyệt cấp 1
    PENDING_CEO = 'pending_ceo',  'Chờ CEO duyệt'   # qua cấp 1, vượt ngưỡng
    REJECTED    = 'rejected',     'Từ chối'
    PENDING     = 'pending_sign', 'Chờ ký'          # đã duyệt xong — chờ ký
    ACTIVE      = 'active',       'Hiệu lực'
    EXPIRED     = 'expired',      'Hết hạn'
    CANCELLED   = 'cancelled',    'Hủy'


class Contract(BaseModel, SoftDeleteMixin):
    """Hợp đồng khung/đơn — sinh từ Quote đã duyệt hoặc tạo trực tiếp."""
    code      = models.CharField(max_length=30, unique=True)   # 'HD-2024-021'
    customer  = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='contracts',
    )
    quote     = models.ForeignKey(
        Quote, on_delete=models.SET_NULL, null=True, blank=True, related_name='contracts',
    )
    title      = models.CharField(max_length=200, blank=True)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # % chiết khấu — định tuyến duyệt
    value_vnd  = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    paid_vnd   = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    status     = models.CharField(
        max_length=20, choices=ContractStatus.choices,
        default=ContractStatus.DRAFT, db_index=True,
    )
    start_date = models.DateField(null=True, blank=True)
    end_date   = models.DateField(null=True, blank=True)
    owner      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='owned_contracts',
    )
    notes      = models.TextField(blank=True)
    # Duyệt 2 cấp (như Báo giá / Đơn mua): cấp 1 = manager, cấp 2 = CEO (vượt ngưỡng).
    l1_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='l1_approved_contracts')
    l1_approved_at = models.DateTimeField(null=True, blank=True)
    l2_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='l2_approved_contracts')
    l2_approved_at = models.DateTimeField(null=True, blank=True)
    approved_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='approved_contracts')

    class Meta:
        db_table = 'crm_contract'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['status', 'customer'], name='crm_contract_status_idx'),
            models.Index(fields=['owner', '-created_at'], name='crm_contract_owner_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.customer.name}"

    def within_sale_authority(self) -> bool:
        """Chiết khấu ≤ hạn mức sale → không cần duyệt (tự duyệt)."""
        return float(self.discount_pct or 0) <= getattr(settings, 'DISCOUNT_SALE_MAX_PCT', 5)

    def requires_l2(self) -> bool:
        """Chiết khấu > hạn mức manager → cần CEO duyệt (cấp 2)."""
        return float(self.discount_pct or 0) > getattr(settings, 'DISCOUNT_MANAGER_MAX_PCT', 10)


class ActivityType(models.TextChoices):
    CALL    = 'call',    'Gọi điện'
    EMAIL   = 'email',   'Email'
    MEETING = 'meeting', 'Gặp mặt'
    ZALO    = 'zalo',    'Zalo'
    OTHER   = 'other',   'Khác'


class Activity(BaseModel):
    """Nhật ký hoạt động chăm sóc khách hàng (cuộc gọi/email/gặp mặt)."""
    customer      = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='activities',
    )
    opportunity   = models.ForeignKey(
        Opportunity, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activities',
    )
    activity_type = models.CharField(
        max_length=20, choices=ActivityType.choices, default=ActivityType.CALL,
    )
    content       = models.TextField(blank=True)
    activity_date = models.DateTimeField(default=timezone.now, db_index=True)
    # Ghi âm cuộc gọi/tiếp xúc + recap
    recording  = models.ForeignKey(
        'storage.FileObject', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',   # file ghi âm (audio)
    )
    recap_file = models.ForeignKey(
        'storage.FileObject', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',   # file recap (Word/PDF)
    )
    recap_text = models.TextField(blank=True)   # văn bản recap từ ghi âm
    owner         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='activities',
    )

    class Meta:
        db_table = 'crm_activity'
        ordering = ['-activity_date']
        indexes  = [
            models.Index(fields=['customer', '-activity_date'], name='crm_activity_cust_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.get_activity_type_display()} — {self.customer_id}"
