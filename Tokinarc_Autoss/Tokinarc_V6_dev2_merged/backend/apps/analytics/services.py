"""
Tokinarc V6.C — apps/analytics/services.py

CEO dashboard aggregations. Production (B.2 §7) dùng materialized view refresh
bằng cron; ở app layer ta tính trực tiếp từ bảng live để code chạy ngay không
phụ thuộc MV. Khi bật MV, thay thân hàm bằng query đọc MV — chữ ký giữ nguyên.

V6.C-fix:
  - Bỏ `__import__('datetime')` xấu; dùng `from datetime import timedelta` ở đầu.
  - Defensive imports cho Lead/Opportunity dùng try/except ở module level (rõ hơn
    hasattr check trong hàm).
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncMonth

# Defensive imports — CRM models có thể chưa được mở rộng
try:
    from apps.crm.models import Lead          # type: ignore
    _HAS_LEAD = True
except ImportError:
    _HAS_LEAD = False

try:
    from apps.crm.models import Opportunity   # type: ignore
    _HAS_OPPORTUNITY = True
except ImportError:
    _HAS_OPPORTUNITY = False


def kpi_overview() -> dict:
    from apps.sales.models import SalesOrder
    from apps.crm.models import Customer

    orders = SalesOrder.objects.filter(status__in=['active', 'shipping', 'completed'])
    agg = orders.aggregate(revenue=Sum('total_vnd'), paid=Sum('paid_vnd'))
    revenue = agg['revenue'] or 0
    paid    = agg['paid']    or 0

    open_leads = 0
    if _HAS_LEAD:
        open_leads = Lead.objects.filter(status__in=['new', 'processing']).count()

    return {
        'revenue_vnd':    revenue,
        'collected_vnd':  paid,
        'debt_vnd':       revenue - paid,
        'order_count':    orders.count(),
        'customer_count': Customer.objects.filter(deleted_at__isnull=True).count(),
        'open_leads':     open_leads,
    }


def revenue_monthly(year: int | None = None) -> list[dict]:
    from apps.sales.models import SalesOrder
    qs = SalesOrder.objects.filter(status__in=['active', 'shipping', 'completed'])
    if year:
        qs = qs.filter(issued_date__year=year)
    rows = (qs.annotate(m=TruncMonth('issued_date'))
            .values('m').annotate(revenue=Sum('total_vnd'), orders=Count('id'))
            .order_by('m'))
    return [{'month':       r['m'].strftime('%Y-%m') if r['m'] else None,
             'revenue_vnd': r['revenue'] or 0,
             'orders':      r['orders']} for r in rows]


def revenue_by_segment() -> list[dict]:
    from apps.sales.models import SalesOrder
    rows = (SalesOrder.objects.filter(status__in=['active', 'shipping', 'completed'])
            .values('customer__segment')
            .annotate(revenue=Sum('total_vnd'), orders=Count('id'))
            .order_by('-revenue'))
    return [{'segment':     r['customer__segment'],
             'revenue_vnd': r['revenue'] or 0,
             'orders':      r['orders']} for r in rows]


def debt_aging() -> list[dict]:
    from apps.sales.models import SalesOrder
    today = date.today()
    qs = (SalesOrder.objects
          .filter(status__in=['active', 'shipping', 'completed'],
                  total_vnd__gt=F('paid_vnd'))
          .select_related('customer'))
    out = []
    for o in qs:
        # Tính due date theo payment_terms
        if o.payment_terms == 'net_30':
            due = o.issued_date + timedelta(days=30)
        elif o.payment_terms == 'net_60':
            due = o.issued_date + timedelta(days=60)
        else:
            due = o.issued_date
        overdue = max(0, (today - due).days)
        bucket = ('current' if overdue == 0
                  else '1-30'  if overdue <= 30
                  else '31-60' if overdue <= 60
                  else '60+')
        out.append({
            'code':         o.code,
            'customer':     o.customer.name,
            'amount_due':   o.total_vnd - o.paid_vnd,
            'days_overdue': overdue,
            'bucket':       bucket,
        })
    return out


def payable_summary() -> dict:
    """Công nợ phải TRẢ NCC: tổng + theo nhà cung cấp (đơn mua chưa trả hết)."""
    from apps.purchasing.models import PurchaseOrder
    qs = (PurchaseOrder.objects
          .filter(status__in=['ordered', 'partial', 'received'], total_vnd__gt=F('paid_vnd'))
          .values('supplier__name')
          .annotate(debt=Sum(F('total_vnd') - F('paid_vnd'))).order_by('-debt'))
    rows = [{'supplier': r['supplier__name'] or '—', 'debt': int(r['debt'])} for r in qs]
    return {'total_payable': sum(r['debt'] for r in rows), 'by_supplier': rows}


def inventory_value(warehouse_code: str | None = None) -> dict:
    """Định giá tồn theo GIÁ VỐN (cost_vnd). Mã chưa có giá vốn → bỏ qua khỏi tổng
    (đếm riêng) để con số không bị thổi phồng theo giá bán."""
    from apps.wms.models import InventoryItem

    qs = InventoryItem.objects.filter(part__isnull=False).select_related('part')
    if warehouse_code:
        qs = qs.filter(bin__zone__warehouse__code=warehouse_code)
    total = 0
    missing_cost = 0
    for i in qs:
        cost = int(i.part.cost_vnd or 0)
        if cost > 0:
            total += i.qty_on_hand * cost
        elif i.qty_on_hand > 0:
            missing_cost += 1
    return {
        'warehouse':           warehouse_code or 'all',
        'inventory_value_vnd': total,           # theo giá vốn
        'sku_count':           qs.count(),
        'sku_missing_cost':    missing_cost,     # số mã còn tồn nhưng chưa có giá vốn
    }


def pipeline_forecast() -> list[dict]:
    """Trống nếu Opportunity chưa có (CRM chưa mở rộng)."""
    if not _HAS_OPPORTUNITY:
        return []
    weighted_expr = ExpressionWrapper(
        F('est_value_vnd') * F('probability') / 100.0,
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    rows = (Opportunity.objects.values('stage')
            .annotate(weighted=Sum(weighted_expr), count=Count('id'))
            .order_by('stage'))
    return [{'stage': r['stage'], 'weighted_vnd': r['weighted'] or 0,
             'count': r['count']} for r in rows]
