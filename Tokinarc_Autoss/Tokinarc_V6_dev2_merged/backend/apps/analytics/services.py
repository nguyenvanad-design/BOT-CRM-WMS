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


def inventory_aging() -> dict:
    """Tuổi tồn theo received_at (ngày nhập đầu — FIFO). Bucket + giá trị theo GIÁ VỐN.
    Giúp thấy vốn đang chôn ở hàng để lâu."""
    from apps.wms.models import InventoryItem

    today = date.today()
    order = ['0-30', '31-90', '91-180', '180+', 'unknown']
    buckets = {k: {'lines': 0, 'qty': 0, 'value_vnd': 0} for k in order}
    qs = InventoryItem.objects.filter(part__isnull=False, qty_on_hand__gt=0).select_related('part')
    for i in qs:
        cost = int(i.part.cost_vnd or 0)
        if not i.received_at:
            key = 'unknown'
        else:
            age = (today - i.received_at.date()).days
            key = '0-30' if age <= 30 else '31-90' if age <= 90 else '91-180' if age <= 180 else '180+'
        b = buckets[key]
        b['lines'] += 1
        b['qty'] += i.qty_on_hand
        b['value_vnd'] += i.qty_on_hand * cost
    return {
        'buckets': [{'bucket': k, **buckets[k]} for k in order],
        'total_value_vnd': sum(b['value_vnd'] for b in buckets.values()),
    }


def dead_stock(days: int = 90) -> dict:
    """Hàng CHẬM/CHẾT: còn tồn nhưng KHÔNG xuất trong `days` ngày (hoặc chưa từng xuất).
    Trả về danh sách theo vốn chôn giảm dần (tiền chết nhiều nhất lên đầu)."""
    from django.db.models import Max

    from apps.wms.models import InventoryItem, StockMovement

    cutoff = date.today() - timedelta(days=days)
    # Lần XUẤT gần nhất (delta < 0) theo part.
    last_out = dict(
        StockMovement.objects.filter(delta__lt=0, part__isnull=False)
        .values_list('part').annotate(last=Max('ts')).values_list('part', 'last'))

    rows: dict = {}
    for i in (InventoryItem.objects.filter(part__isnull=False, qty_on_hand__gt=0)
              .select_related('part')):
        r = rows.setdefault(i.part_id, {
            'part_no': i.part_id,
            'name': getattr(i.part, 'display_name_vi', '') or str(i.part_id),
            'qty': 0, 'cost_vnd': int(i.part.cost_vnd or 0)})
        r['qty'] += i.qty_on_hand

    out = []
    for pid, r in rows.items():
        last = last_out.get(pid)
        last_d = last.date() if last else None
        if last_d is None or last_d < cutoff:
            out.append({
                'part_no': r['part_no'], 'name': r['name'], 'qty': r['qty'],
                'value_vnd': r['qty'] * r['cost_vnd'],
                'last_out': last_d.isoformat() if last_d else None,
                'days_idle': (date.today() - last_d).days if last_d else None,
            })
    out.sort(key=lambda x: -x['value_vnd'])
    return {
        'days': days, 'count': len(out),
        'tied_value_vnd': sum(x['value_vnd'] for x in out),
        'results': out[:100],
    }


def reorder_suggestions(days: int = 60, lead_time_days: int = 14, target_days: int = 30) -> dict:
    """ĐỀ NGHỊ NHẬP HÀNG dựa trên tốc độ bán (xuất) gần đây + tồn khả dụng.
    Mã 'cần nhập' = đủ dùng < lead_time NGÀY, hoặc tồn ≤ định mức (min_level).
    suggest_qty = bù đủ dùng target_days (hoặc bù về min)."""
    from apps.wms.models import InventoryItem, StockMovement

    since = date.today() - timedelta(days=days)
    sold: dict = {}
    for r in (StockMovement.objects.filter(delta__lt=0, part__isnull=False, ts__date__gte=since)
              .values('part').annotate(q=Sum('delta'))):
        sold[r['part']] = -int(r['q'] or 0)   # delta âm → đảo dấu thành SL bán

    rows: dict = {}
    for i in InventoryItem.objects.filter(part__isnull=False).select_related('part'):
        r = rows.setdefault(i.part_id, {
            'part_no': i.part_id,
            'name': getattr(i.part, 'display_name_vi', '') or str(i.part_id),
            'available': 0, 'min': 0})
        r['available'] += (i.qty_on_hand - i.qty_reserved)
        r['min'] = max(r['min'], i.min_level or 0)

    out = []
    for pid, r in rows.items():
        daily = sold.get(pid, 0) / days if sold.get(pid) else 0.0
        avail = r['available']
        cover = (avail / daily) if daily > 0 else None
        need = (cover is not None and cover < lead_time_days) or (r['min'] > 0 and avail <= r['min'])
        if not need:
            continue
        target_qty = int(round(daily * target_days)) if daily > 0 else r['min']
        suggest = max(target_qty - avail, (r['min'] - avail) if r['min'] else 0)
        if suggest <= 0:
            suggest = max(r['min'] - avail, 1)
        out.append({
            'part_no': r['part_no'], 'name': r['name'], 'available': avail,
            'min_level': r['min'], 'daily_sold': round(daily, 2),
            'days_cover': round(cover, 1) if cover is not None else None,
            'suggest_qty': suggest,
        })
    out.sort(key=lambda x: (x['days_cover'] is None, x['days_cover'] if x['days_cover'] is not None else 1e9))
    return {'days': days, 'lead_time_days': lead_time_days, 'count': len(out), 'results': out[:50]}


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


_ACTIVE_ORDER = ['active', 'shipping', 'completed']


def revenue_summary(period: str = 'month') -> dict:
    """Doanh thu theo kỳ (today|month|year|all): tổng + đã thu + số đơn."""
    from apps.sales.models import SalesOrder
    qs = SalesOrder.objects.filter(status__in=_ACTIVE_ORDER)
    today = date.today()
    if period == 'today':
        qs = qs.filter(issued_date=today); label = f"hôm nay ({today:%d/%m/%Y})"
    elif period == 'year':
        qs = qs.filter(issued_date__year=today.year); label = f"năm {today.year}"
    elif period == 'all':
        label = "toàn thời gian"
    else:
        qs = qs.filter(issued_date__year=today.year, issued_date__month=today.month)
        label = f"tháng {today.month}/{today.year}"
    agg = qs.aggregate(rev=Sum('total_vnd'), paid=Sum('paid_vnd'))
    return {'period': period, 'label': label, 'revenue_vnd': int(agg['rev'] or 0),
            'paid_vnd': int(agg['paid'] or 0), 'count': qs.count()}


def customer_debt(name: str | None = None) -> dict:
    """Công nợ 1 khách (name) hoặc tổng quan top khách nợ nhiều."""
    from apps.sales.models import SalesOrder
    from apps.crm.models import Customer

    if name:
        cust = (Customer.objects.filter(name__icontains=name, deleted_at__isnull=True).first()
                or Customer.objects.filter(code__icontains=name).first())
        if not cust:
            return {'found': False, 'query': name}
        agg = (SalesOrder.objects.filter(customer=cust, status__in=_ACTIVE_ORDER)
               .aggregate(t=Sum('total_vnd'), p=Sum('paid_vnd')))
        total, paid = int(agg['t'] or 0), int(agg['p'] or 0)
        return {'found': True, 'name': cust.name, 'total_vnd': total,
                'paid_vnd': paid, 'debt_vnd': total - paid}

    rows = (SalesOrder.objects.filter(status__in=_ACTIVE_ORDER, total_vnd__gt=F('paid_vnd'))
            .values('customer__name')
            .annotate(debt=Sum(F('total_vnd') - F('paid_vnd')))
            .order_by('-debt')[:5])
    results = [{'name': r['customer__name'], 'debt_vnd': int(r['debt'] or 0)} for r in rows]
    return {'found': None, 'results': results, 'total_vnd': sum(r['debt_vnd'] for r in results)}


def top_customers(limit: int = 5) -> list[dict]:
    """Top khách hàng theo doanh số (đơn active/shipping/completed)."""
    from apps.sales.models import SalesOrder
    rows = (SalesOrder.objects.filter(status__in=_ACTIVE_ORDER)
            .values('customer__name').annotate(revenue=Sum('total_vnd'))
            .order_by('-revenue')[:max(1, limit)])
    return [{'name': r['customer__name'], 'revenue_vnd': int(r['revenue'] or 0)} for r in rows]


def dormant_customers(months: int = 3) -> dict:
    """Khách hàng không phát sinh đơn trong `months` tháng gần đây (nguy cơ rời)."""
    from apps.sales.models import SalesOrder
    from apps.crm.models import Customer
    cutoff = date.today() - timedelta(days=months * 30)
    recent = set(SalesOrder.objects.filter(issued_date__gte=cutoff)
                 .values_list('customer_id', flat=True))
    qs = Customer.objects.filter(deleted_at__isnull=True).exclude(id__in=recent)
    return {'months': months, 'count': qs.count(),
            'names': list(qs.values_list('name', flat=True)[:10])}


def executive_metrics() -> dict:
    """Gom TOÀN BỘ số liệu điều hành + hoạt động (chuyển từ assistant._gather_*).
    Sống ở tầng API để trợ lý nội bộ đọc QUA API (không truy vấn DB trực tiếp)."""
    from apps.crm.models import Customer, Lead, Opportunity, Ticket
    from apps.sales.models import SalesOrder
    from apps.wms.models import InventoryItem

    today = date.today()
    active = SalesOrder.objects.filter(status__in=_ACTIVE_ORDER)
    month = active.filter(issued_date__year=today.year, issued_date__month=today.month)
    rev_month = month.aggregate(s=Sum('total_vnd'))['s'] or 0
    paid_month = month.aggregate(s=Sum('paid_vnd'))['s'] or 0
    debt = active.filter(total_vnd__gt=F('paid_vnd')).aggregate(
        d=Sum(F('total_vnd') - F('paid_vnd')))['d'] or 0
    overdue = sum(x['amount_due'] for x in debt_aging() if x['days_overdue'] > 0)
    top = active.values('customer__name').annotate(r=Sum('total_vnd')).order_by('-r').first()
    weighted = sum(float(x['weighted_vnd']) for x in pipeline_forecast())
    cutoff = today - timedelta(days=90)
    recent = set(SalesOrder.objects.filter(issued_date__gte=cutoff).values_list('customer_id', flat=True))
    dormant = Customer.objects.filter(deleted_at__isnull=True).exclude(id__in=recent).count()
    inv = inventory_value()

    m = {
        'revenue_month':        int(rev_month),
        'collected_month':      int(paid_month),
        'debt_total':           int(debt),
        'overdue':              int(overdue),
        'top_customer':         top['customer__name'] if top else None,
        'top_customer_revenue': int(top['r']) if top else 0,
        'pipeline_weighted':    int(weighted),
        'customers':            Customer.objects.filter(deleted_at__isnull=True).count(),
        'dormant_customers':    dormant,
        'open_leads':           Lead.objects.filter(status__in=['new', 'contacted']).count(),
        'open_opportunities':   Opportunity.objects.exclude(stage__in=['won', 'lost']).count(),
        'open_tickets':         Ticket.objects.filter(status__in=['open', 'in_progress']).count(),
        'urgent_tickets':       Ticket.objects.filter(status__in=['open', 'in_progress'], priority='urgent').count(),
        'inventory_value':      int(inv['inventory_value_vnd']),
        'sku_count':            inv['sku_count'],
        'low_stock':            InventoryItem.objects.filter(qty_on_hand__lte=F('min_level')).count(),
    }
    m['hoat_dong'] = _executive_activities()
    return m


def _executive_activities(days: int = 30, max_items: int = 12) -> dict:
    """Recap cuộc gặp/gọi + đếm ghi âm + hoạt động kho (chuyển từ assistant._gather_activities)."""
    from django.utils import timezone as _tz

    from apps.crm.models import Activity, Visit
    from apps.wms.models import StockMovement
    try:
        from apps.wms.models import CycleCount
    except Exception:  # noqa: BLE001
        CycleCount = None

    today = date.today()
    since_d = today - timedelta(days=days)
    since_dt = _tz.now() - timedelta(days=days)

    visits = (Visit.objects.filter(visit_date__gte=since_d)
              .select_related('customer', 'owner').order_by('-visit_date'))
    acts = (Activity.objects.filter(activity_date__gte=since_dt)
            .select_related('customer', 'owner').order_by('-activity_date'))

    def _clip(s, n=240):
        return (s or '').strip().replace('\n', ' ')[:n]

    visit_recaps = [{
        'kh': v.customer.name if v.customer_id else '',
        'ngay': str(v.visit_date), 'sale': v.owner.username if v.owner_id else '',
        'recap': _clip(v.recap_text or v.summary), 'co_ghi_am': bool(v.recording_id),
        'viec_tiep': v.next_action or '',
    } for v in visits[:max_items] if (v.recap_text or v.summary)]

    call_recaps = [{
        'kh': a.customer.name if a.customer_id else '',
        'loai': a.get_activity_type_display(),
        'recap': _clip(a.recap_text or a.content), 'co_ghi_am': bool(a.recording_id),
    } for a in acts[:max_items] if (a.recap_text or a.content)]

    wh = {
        'phieu_nhap': StockMovement.objects.filter(ts__gte=since_dt, delta__gt=0).count(),
        'phieu_xuat': StockMovement.objects.filter(ts__gte=since_dt, delta__lt=0).count(),
        'dieu_chinh_ton': StockMovement.objects.filter(ts__gte=since_dt, reason='adjust').count(),
    }
    if CycleCount is not None:
        wh['kiem_ke'] = CycleCount.objects.filter(created_at__gte=since_dt).count()

    return {
        'ky_ngay': days,
        'so_cuoc_gap': visits.count(),
        'cuoc_gap_co_ghi_am': visits.exclude(recording__isnull=True).count(),
        'so_cuoc_goi_email': acts.count(),
        'goi_email_co_ghi_am': acts.exclude(recording__isnull=True).count(),
        'recap_cuoc_gap': visit_recaps,
        'recap_cuoc_goi': call_recaps,
        'hoat_dong_kho': wh,
    }
