"""
Tokinarc V6 — apps/analytics/assistant.py

Trợ lý CRM NỘI BỘ (tách hẳn chatbot bán hàng cho khách). Trả lời câu hỏi nghiệp
vụ: doanh thu, công nợ, khách hàng — bằng cách:

  1. Hiểu câu hỏi → intent + tham số (LLM Gemini nếu có key, fallback từ khóa).
  2. Truy vấn DB thật (số liệu KHÔNG do LLM bịa — luôn tính từ Postgres).
  3. Soạn câu trả lời tiếng Việt từ số liệu thật.

MVP intent: revenue | customer_debt | top_customers | dormant_customers.
Bảo mật: chỉ manager/admin gọi (xem AssistantQueryView). KHÁC chatbot khách —
bot khách tuyệt đối không được chạm data này.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from django.db.models import F, Sum

_ACTIVE = ['active', 'shipping', 'completed']


# ── Tiền VND ──────────────────────────────────────────────────────────────
def _vnd(n) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return '0 ₫'
    if abs(n) >= 1_000_000_000:
        return f"{n / 1e9:.2f}".rstrip('0').rstrip('.') + ' tỷ ₫'
    if abs(n) >= 1_000_000:
        return f"{round(n / 1e6):,}".replace(',', '.') + ' tr ₫'
    return f"{n:,}".replace(',', '.') + ' ₫'


# ── Tools (đọc DB thật) ─────────────────────────────────────────────────────
def tool_revenue(period: str = 'month') -> str:
    from apps.sales.models import SalesOrder
    qs = SalesOrder.objects.filter(status__in=_ACTIVE)
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
    rev = agg['rev'] or 0
    cnt = qs.count()
    return (f"Doanh thu {label}: **{_vnd(rev)}** từ {cnt} đơn hàng "
            f"(đã thu {_vnd(agg['paid'] or 0)}).") if cnt else \
           f"Doanh thu {label}: chưa có đơn hàng nào."


def tool_customer_debt(name: str | None = None) -> str:
    from apps.sales.models import SalesOrder
    from apps.crm.models import Customer

    if name:
        cust = (Customer.objects.filter(name__icontains=name, deleted_at__isnull=True).first()
                or Customer.objects.filter(code__icontains=name).first())
        if not cust:
            return f"Không tìm thấy khách hàng khớp \"{name}\"."
        agg = (SalesOrder.objects.filter(customer=cust, status__in=_ACTIVE)
               .aggregate(t=Sum('total_vnd'), p=Sum('paid_vnd')))
        debt = (agg['t'] or 0) - (agg['p'] or 0)
        if debt <= 0:
            return f"**{cust.name}** hiện không còn công nợ (đã thanh toán đủ)."
        return f"**{cust.name}** còn nợ **{_vnd(debt)}** (tổng đơn {_vnd(agg['t'] or 0)}, đã trả {_vnd(agg['p'] or 0)})."

    # Tổng quan công nợ + top khách nợ nhiều
    rows = (SalesOrder.objects.filter(status__in=_ACTIVE, total_vnd__gt=F('paid_vnd'))
            .values('customer__name')
            .annotate(debt=Sum(F('total_vnd') - F('paid_vnd')))
            .order_by('-debt')[:5])
    if not rows:
        return "Hiện không có công nợ phải thu."
    total = sum(r['debt'] for r in rows)
    lines = '\n'.join(f"• {r['customer__name']}: {_vnd(r['debt'])}" for r in rows)
    return f"Tổng công nợ phải thu (top {len(rows)}): **{_vnd(total)}**\n{lines}"


def tool_top_customers(limit: int = 5) -> str:
    from apps.sales.models import SalesOrder
    rows = (SalesOrder.objects.filter(status__in=_ACTIVE)
            .values('customer__name')
            .annotate(rev=Sum('total_vnd')).order_by('-rev')[:limit])
    if not rows:
        return "Chưa có dữ liệu doanh số theo khách hàng."
    lines = '\n'.join(f"{i+1}. {r['customer__name']}: {_vnd(r['rev'])}"
                      for i, r in enumerate(rows))
    return f"Top {len(rows)} khách hàng theo doanh số:\n{lines}"


def tool_dormant_customers(months: int = 3) -> str:
    from datetime import timedelta

    from apps.sales.models import SalesOrder
    from apps.crm.models import Customer

    cutoff = date.today() - timedelta(days=months * 30)
    recent_ids = set(SalesOrder.objects.filter(issued_date__gte=cutoff)
                     .values_list('customer_id', flat=True))
    dormant = (Customer.objects.filter(deleted_at__isnull=True)
               .exclude(id__in=recent_ids))
    names = list(dormant.values_list('name', flat=True)[:10])
    if not names:
        return f"Tất cả khách hàng đều có giao dịch trong {months} tháng gần đây."
    lines = '\n'.join(f"• {n}" for n in names)
    return (f"Có {dormant.count()} khách hàng không mua trong {months} tháng qua "
            f"(nguy cơ rời):\n{lines}")


# ── Router: hiểu câu hỏi → intent + params ──────────────────────────────────
def _from_chatbot_env(var: str) -> str:
    """Đọc 1 biến từ chatbot/.env (dev, cùng máy)."""
    try:
        env = (Path(__file__).resolve().parents[3] / 'chatbot' / '.env').read_text(encoding='utf-8')
        m = re.search(rf'^{var}=(.*)$', env, re.M)
        return m.group(1).strip() if m else ''
    except OSError:
        return ''


def _gemini_key() -> str:
    return os.getenv('GEMINI_API_KEY', '') or _from_chatbot_env('GEMINI_API_KEY')


def _gemini_model() -> str:
    return (os.getenv('GEMINI_MODEL', '') or _from_chatbot_env('GEMINI_MODEL')
            or 'gemini-2.5-flash')


_INTENT_SCHEMA = (
    "Bạn là bộ phân loại ý định cho trợ lý CRM nội bộ. Cho câu hỏi tiếng Việt, "
    "TRẢ VỀ DUY NHẤT một JSON, không giải thích, dạng: "
    '{"intent": "...", "customer_name": "", "period": "", "months": 3}. '
    "intent ∈ [revenue, customer_debt, top_customers, dormant_customers, unknown]. "
    "period ∈ [today, month, year, all] (chỉ cho revenue). "
    "customer_name: tên KH nếu hỏi công nợ 1 KH cụ thể, ngược lại để rỗng. "
    "months: số tháng cho dormant_customers (mặc định 3)."
)


def _llm_intent(question: str) -> dict | None:
    key = _gemini_key()
    if not key:
        return None
    model = _gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": _INTENT_SCHEMA + "\n\nCâu hỏi: " + question}]}],
        # thinkingBudget=0: tắt "thinking" của gemini-2.5 (nếu không sẽ ăn hết token output)
        "generationConfig": {"temperature": 0, "maxOutputTokens": 256,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read())
        text = data['candidates'][0]['content']['parts'][0]['text']
        m = re.search(r'\{.*\}', text, re.S)
        return json.loads(m.group(0)) if m else None
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError):
        return None


def _keyword_intent(q: str) -> dict:
    ql = q.lower()
    if any(k in ql for k in ('công nợ', 'cong no', 'còn nợ', 'no bao nhieu', 'nợ', 'phải thu')):
        # Thử bắt tên KH sau từ khóa (đơn giản): cụm chữ hoa hoặc sau "của"
        m = re.search(r'(?:của|cua)\s+([\w\sÀ-ỹ]+?)(?:\s+còn|\s+nợ|\?|$)', q, re.I)
        return {'intent': 'customer_debt', 'customer_name': (m.group(1).strip() if m else '')}
    if any(k in ql for k in ('chưa mua', 'chua mua', 'ngủ đông', 'ngu dong', 'nguy cơ rời', 'rời bỏ')):
        mm = re.search(r'(\d+)\s*tháng', ql)
        return {'intent': 'dormant_customers', 'months': int(mm.group(1)) if mm else 3}
    if any(k in ql for k in ('top', 'nhiều nhất', 'nhieu nhat', 'lớn nhất', 'đóng góp')):
        return {'intent': 'top_customers'}
    if any(k in ql for k in ('doanh thu', 'doanh số', 'doanh so', 'revenue')):
        if any(k in ql for k in ('hôm nay', 'hom nay', 'today')):
            period = 'today'
        elif any(k in ql for k in ('năm', 'nam nay', 'year')):
            period = 'year'
        else:
            period = 'month'
        return {'intent': 'revenue', 'period': period}
    return {'intent': 'unknown'}


def _detect_customer(q: str) -> str:
    """Đối chiếu câu hỏi với tên KH trong DB (bắt tên dù LLM/regex bỏ sót)."""
    from apps.crm.models import Customer
    ql = q.lower()
    for n in Customer.objects.filter(deleted_at__isnull=True).values_list('name', flat=True):
        if n and n.lower() in ql:
            return n
    return ''


def answer(question: str) -> str:
    """Điểm vào chính: câu hỏi → câu trả lời (số liệu thật từ DB)."""
    intent = _llm_intent(question) or _keyword_intent(question)
    name = intent.get('intent', 'unknown')

    if name == 'revenue':
        return tool_revenue(intent.get('period') or 'month')
    if name == 'customer_debt':
        cust_name = intent.get('customer_name') or _detect_customer(question)
        return tool_customer_debt(cust_name or None)
    if name == 'top_customers':
        return tool_top_customers()
    if name == 'dormant_customers':
        return tool_dormant_customers(int(intent.get('months') or 3))

    return ("Em là trợ lý CRM nội bộ. Em trả lời được về: **doanh thu** (hôm nay/"
            "tháng/năm), **công nợ** khách hàng, **top khách hàng**, và **khách "
            "chưa mua** lâu. Anh/chị thử hỏi cụ thể hơn nhé.")


# ── Executive summary (tổng hợp liên phòng ban) ─────────────────────────────
def _gather_metrics() -> dict:
    """Gom số liệu THẬT từ tất cả phòng ban (Sales/CRM/Dịch vụ/Kho)."""
    from datetime import timedelta

    from django.db.models import F

    from apps.crm.models import Customer, Lead, Opportunity, Ticket
    from apps.sales.models import SalesOrder
    from apps.wms.models import InventoryItem
    from . import services

    today = date.today()
    active = SalesOrder.objects.filter(status__in=_ACTIVE)
    month = active.filter(issued_date__year=today.year, issued_date__month=today.month)
    rev_month = month.aggregate(s=Sum('total_vnd'))['s'] or 0
    paid_month = month.aggregate(s=Sum('paid_vnd'))['s'] or 0
    debt = active.filter(total_vnd__gt=F('paid_vnd')).aggregate(
        d=Sum(F('total_vnd') - F('paid_vnd')))['d'] or 0
    overdue = sum(x['amount_due'] for x in services.debt_aging() if x['days_overdue'] > 0)
    top = active.values('customer__name').annotate(r=Sum('total_vnd')).order_by('-r').first()
    weighted = sum(float(x['weighted_vnd']) for x in services.pipeline_forecast())
    cutoff = today - timedelta(days=90)
    recent = set(SalesOrder.objects.filter(issued_date__gte=cutoff).values_list('customer_id', flat=True))
    dormant = Customer.objects.filter(deleted_at__isnull=True).exclude(id__in=recent).count()
    inv = services.inventory_value()

    return {
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


def _template_summary(m: dict) -> str:
    """Tóm tắt mặc định (không cần LLM) — ghép câu từ số liệu thật."""
    lines = [
        "**Tổng quan**",
        f"Doanh thu tháng này đạt {_vnd(m['revenue_month'])} (đã thu {_vnd(m['collected_month'])}). "
        f"Công nợ phải thu {_vnd(m['debt_total'])}, trong đó quá hạn {_vnd(m['overdue'])}. "
        f"Pipeline weighted {_vnd(m['pipeline_weighted'])} từ {m['open_opportunities']} cơ hội đang mở.",
        "",
        "**Kinh doanh (Sales/CRM)**",
        f"• {m['customers']} khách hàng, {m['open_leads']} lead đang theo.",
        f"• Khách hàng đóng góp lớn nhất: {m['top_customer'] or '—'} ({_vnd(m['top_customer_revenue'])}).",
        f"• {m['dormant_customers']} khách chưa mua >3 tháng (nguy cơ rời).",
        "",
        "**Dịch vụ**",
        f"• {m['open_tickets']} ticket đang mở" + (f", {m['urgent_tickets']} khẩn." if m['urgent_tickets'] else "."),
        "",
        "**Kho vận**",
        f"• Giá trị tồn kho {_vnd(m['inventory_value'])} ({m['sku_count']} SKU), {m['low_stock']} mặt hàng sắp hết.",
    ]
    return "\n".join(lines)


def _llm_summary(m: dict) -> str | None:
    """Nhờ Gemini viết tóm tắt điều hành từ metrics thật (không bịa số)."""
    key = _gemini_key()
    if not key:
        return None
    model = _gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    prompt = (
        "Bạn là trợ lý điều hành. Dưới đây là SỐ LIỆU THẬT (VND) của công ty phân phối "
        "súng hàn Tokinarc theo từng phòng ban. Hãy viết một bản TÓM TẮT ĐIỀU HÀNH ngắn "
        "gọn bằng tiếng Việt cho Giám đốc, gồm 4 mục in đậm: **Tổng quan**, **Điểm tích "
        "cực**, **Cần chú ý**, **Khuyến nghị tuần này**. CHỈ dùng đúng số liệu cho sẵn, "
        "KHÔNG bịa thêm số. Ngắn gọn, súc tích.\n\nSỐ LIỆU:\n" + json.dumps(m, ensure_ascii=False)
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1200,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError):
        return None


def executive_summary() -> dict:
    """Tóm tắt toàn bộ hoạt động phòng ban. Số liệu thật, lời do LLM (fallback template)."""
    m = _gather_metrics()
    ai = _llm_summary(m)
    return {
        'summary': ai or _template_summary(m),
        'metrics': m,
        'generated_by': 'ai' if ai else 'template',
    }
