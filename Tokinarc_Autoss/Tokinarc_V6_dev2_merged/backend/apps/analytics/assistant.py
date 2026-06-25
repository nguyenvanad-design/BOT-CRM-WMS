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
    "Bạn là bộ phân loại ý định cho trợ lý NỘI BỘ công ty phân phối súng hàn Tokinarc. "
    "Cho câu hỏi/yêu cầu tiếng Việt, TRẢ VỀ DUY NHẤT một JSON, không giải thích, dạng: "
    '{"intent": "...", "customer_name": "", "period": "", "months": 3, '
    '"items": [{"part_no": "", "qty": 1}], "quote_code": ""}. '
    "intent ∈ [revenue, customer_debt, top_customers, dormant_customers, ceo_report, "
    "evaluate_plan, create_lead, create_quote, create_contract, wms_inbound, wms_outbound, "
    "lookup_doc, unknown]. "
    "Khi tạo lead: lead_name (tên người), company (công ty), phone (SĐT). "
    "period ∈ [today, month, year, all] (chỉ cho revenue). "
    "customer_name: tên KH nếu liên quan 1 KH cụ thể (công nợ / báo giá / hợp đồng). "
    "months: số tháng cho dormant_customers (mặc định 3). "
    "items: danh sách mã phụ tùng + số lượng khi LÀM BÁO GIÁ (create_quote); "
    "rỗng nếu không phải báo giá. "
    "ceo_report = xin tóm tắt điều hành; evaluate_plan = đánh giá kế hoạch/pipeline. "
    "quote_code: mã báo giá (VD BG-0007) khi SOẠN HỢP ĐỒNG từ báo giá đã duyệt."
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
    if any(k in ql for k in ('tạo lead', 'tao lead', 'thêm lead', 'them lead', 'lead mới',
                             'khách tiềm năng', 'khach tiem nang', 'ghi lead')):
        return {'intent': 'create_lead'}
    # Hợp đồng trước báo giá: câu "soạn hợp đồng từ báo giá BG-x" chứa cả 2 từ khóa.
    if any(k in ql for k in ('hợp đồng', 'hop dong', 'soạn hợp đồng', 'lập hợp đồng')):
        return {'intent': 'create_contract'}
    if any(k in ql for k in ('báo giá', 'bao gia', 'tạo báo giá', 'lập báo giá', 'làm báo giá')):
        return {'intent': 'create_quote', 'items': _parse_items(q)}
    if any(k in ql for k in ('nhập kho', 'nhap kho', 'phiếu nhập', 'phieu nhap', 'nhận hàng')):
        return {'intent': 'wms_inbound'}
    if any(k in ql for k in ('xuất kho', 'xuat kho', 'phiếu xuất', 'phieu xuat', 'giao hàng')):
        return {'intent': 'wms_outbound'}
    if any(k in ql for k in ('báo cáo ceo', 'bao cao ceo', 'tóm tắt điều hành', 'tom tat dieu hanh',
                             'báo cáo điều hành', 'executive')):
        return {'intent': 'ceo_report'}
    if any(k in ql for k in ('đánh giá kế hoạch', 'danh gia ke hoach', 'pipeline', 'dự báo', 'du bao',
                             'forecast', 'kế hoạch kinh doanh')):
        return {'intent': 'evaluate_plan'}
    if any(k in ql for k in ('đơn của', 'don cua', 'đơn hàng của', 'don hang cua', 'mua gì', 'lịch sử mua')):
        return {'intent': 'customer_orders'}
    if any(k in ql for k in ('tồn', 'ton kho', 'còn hàng', 'con hang', 'kho còn', 'số lượng tồn')):
        return {'intent': 'stock_lookup'}
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
    if any(k in ql for k in ('tra cứu', 'tra cuu', 'thông tin', 'thong tin', 'thông số',
                             'thong so', 'spec', 'tài liệu', 'tai lieu', 'phụ tùng', 'phu tung',
                             'súng hàn', 'sung han')):
        return {'intent': 'lookup_doc'}
    return {'intent': 'unknown'}


def _detect_customer(q: str) -> str:
    """Đối chiếu câu hỏi với tên KH trong DB (bắt tên dù LLM/regex bỏ sót)."""
    from apps.crm.models import Customer
    ql = q.lower()
    for n in Customer.objects.filter(deleted_at__isnull=True).values_list('name', flat=True):
        if n and n.lower() in ql:
            return n
    return ''


def _parse_items(q: str) -> list[dict]:
    """Trích (mã phụ tùng, số lượng) từ câu tự do — fallback khi không có LLM.

    Bắt mẫu: "5 x 001002", "10 cái 002001", "001002 x3", "2 001003".
    """
    items: list[dict] = []
    seen = set()
    # qty trước mã: "5 x 001002" / "10 cái 002001" / "2 001003"
    for m in re.finditer(r'(\d+)\s*(?:x|cái|cai|chiếc|chiec|pcs|\*)?\s*([0-9]{4,}[A-Za-z0-9\-]*)', q):
        qty, pn = int(m.group(1)), m.group(2)
        if pn not in seen:
            items.append({'part_no': pn, 'qty': max(1, qty)}); seen.add(pn)
    # mã trước qty: "001002 x3"
    for m in re.finditer(r'([0-9]{4,}[A-Za-z0-9\-]*)\s*(?:x|\*)\s*(\d+)', q):
        pn, qty = m.group(1), int(m.group(2))
        if pn not in seen:
            items.append({'part_no': pn, 'qty': max(1, qty)}); seen.add(pn)
    return items


# ── Tool điều hành (đọc) ────────────────────────────────────────────────────
def tool_ceo_report() -> str:
    """Báo cáo điều hành cho CEO (tóm tắt toàn phòng ban, số liệu thật)."""
    return executive_summary()['summary']


def tool_evaluate_plan() -> str:
    """Đánh giá kế hoạch kinh doanh từ pipeline forecast (số liệu thật)."""
    from . import services
    rows = services.pipeline_forecast()
    if not rows:
        return "Chưa có cơ hội nào trong pipeline để đánh giá kế hoạch."
    total_w = sum(float(r['weighted_vnd'] or 0) for r in rows)
    total_cnt = sum(int(r.get('count', 0) or 0) for r in rows)
    lines = [f"• {r['stage']}: {r.get('count', 0)} cơ hội — dự báo có trọng số "
             f"{_vnd(r['weighted_vnd'])}" for r in rows]
    body = '\n'.join(lines)
    return (f"**Đánh giá kế hoạch (pipeline)**\n"
            f"{total_cnt} cơ hội đang mở; **dự báo doanh thu có trọng số "
            f"(weighted): {_vnd(total_w)}**.\n{body}\n"
            f"_Weighted = giá trị cơ hội × xác suất theo giai đoạn._")


# ── Tool ghi: làm báo giá nháp ──────────────────────────────────────────────
def _resolve_customer(name: str, user):
    """Tìm KH theo tên/mã. Non-manager chỉ thấy KH của mình (khớp ownership)."""
    from apps.accounts.roles import is_manager
    from apps.crm.models import Customer
    if not name:
        return None
    qs = Customer.objects.filter(deleted_at__isnull=True)
    if not is_manager(user):
        qs = qs.filter(owner_id=user.id)
    return (qs.filter(name__icontains=name).first()
            or qs.filter(code__icontains=name).first())


def _parse_phone(q: str) -> str:
    m = re.search(r'\b0\d{8,10}\b', q.replace('.', '').replace(' ', ''))
    return m.group(0) if m else ''


def tool_create_lead(user, name: str, company: str = '', phone: str = '', source: str = 'chatbot') -> str:
    """Tạo LEAD (khách tiềm năng) vào CRM, owner = người dùng."""
    from apps.crm.models import Lead
    name = (name or '').strip()
    if not name:
        return ('Cần tên khách tiềm năng. VD: "tạo lead Nguyễn Văn A, công ty ABC, 0901234567".')
    lead = Lead.objects.create(name=name, company=(company or '').strip(),
                               phone=(phone or '').strip(), source=source or 'chatbot',
                               owner=user)
    extra = []
    if lead.company: extra.append(lead.company)
    if lead.phone: extra.append(lead.phone)
    tail = f" ({', '.join(extra)})" if extra else ""
    return (f"✅ Đã ghi **lead: {lead.name}**{tail} vào CRM (trạng thái Mới). "
            f"Vào menu Leads để theo dõi / chuyển thành khách hàng.")


def tool_create_quote(user, customer_name: str, items: list[dict]) -> str:
    """Tạo BÁO GIÁ NHÁP (draft) cho user, lấy giá từ catalog. Cần duyệt sau."""
    from apps.catalog.models import Part
    from apps.crm.models import Quote, QuoteLine
    from apps.crm.views_ext import _next_code

    if not customer_name:
        return "Cần cho biết **tên khách hàng** để lập báo giá. VD: \"làm báo giá cho Công ty ABC: 5 x 001002\"."
    cust = _resolve_customer(customer_name, user)
    if not cust:
        return (f"Không tìm thấy khách hàng khớp \"{customer_name}\" (trong phạm vi của bạn). "
                f"Kiểm tra lại tên/mã KH.")
    if not items:
        return (f"Đã xác định KH **{cust.name}** nhưng chưa có dòng hàng. "
                f"Nêu mã phụ tùng + số lượng, VD: \"5 x 001002, 10 cái 002001\".")

    quote = Quote.objects.create(customer=cust, owner=user, code=_next_code(Quote, 'BG'))
    found, missing = [], []
    for it in items:
        pn = str(it.get('part_no', '')).strip()
        qty = max(1, int(it.get('qty', 1) or 1))
        if not pn:
            continue
        part = Part.objects.filter(tokin_part_no=pn).first()
        if not part:
            missing.append(pn); continue
        QuoteLine.objects.create(
            quote=quote, part_no=pn, part_name=part.display_name_vi or '',
            qty=qty, unit_price_vnd=part.price_vnd or 0,
        )
        found.append((pn, part.display_name_vi or pn, qty, int(part.price_vnd or 0)))

    if not found:
        quote.delete()
        return (f"Không tạo được báo giá: không tìm thấy mã phụ tùng nào hợp lệ "
                f"({', '.join(missing)}).")
    quote.recompute_total()
    quote.save(update_fields=['total_vnd'])
    # Báo manager+: báo giá tạo qua bot cũng cần duyệt (đồng bộ với đường API).
    from apps.accounts.roles import MANAGER_ROLES
    from apps.common.models import notify_roles
    notify_roles(MANAGER_ROLES, 'quote_approval',
                 f"Báo giá {quote.code} ({cust.name}) cần duyệt.",
                 link='/ceo/approvals', exclude_user=user)

    rows = '\n'.join(f"• {n} (`{pn}`) × {qty} = {_vnd(p * qty)}" for pn, n, qty, p in found)
    note = f"\n⚠️ Không thấy mã: {', '.join(missing)}" if missing else ""
    lvl = " — giá trị lớn, sẽ cần CEO duyệt cấp 2" if quote.requires_l2() else ""
    return (f"✅ Đã tạo **báo giá nháp {quote.code}** cho **{cust.name}**:\n{rows}\n"
            f"**Tổng: {_vnd(quote.total_vnd)}**{lvl}.{note}\n"
            f"Báo giá đang ở trạng thái *Nháp* — vào màn Báo giá để gửi & trình duyệt.")


def tool_create_contract(user, customer_name: str, quote_code: str) -> str:
    """Soạn HỢP ĐỒNG NHÁP: ưu tiên từ báo giá đã duyệt (quote_code), hoặc cho 1 KH."""
    from apps.accounts.roles import is_manager
    from apps.crm.contracts_activities import _next_contract_code
    from apps.crm.models import Contract, Quote, QuoteStatus

    # Từ báo giá đã duyệt
    if quote_code:
        qs = Quote.objects.filter(code__iexact=quote_code)
        if not is_manager(user):
            qs = qs.filter(owner_id=user.id)
        quote = qs.first()
        if not quote:
            return f"Không tìm thấy báo giá **{quote_code}** (trong phạm vi của bạn)."
        if quote.status not in (QuoteStatus.APPROVED, QuoteStatus.CONVERTED):
            return (f"Báo giá {quote.code} đang *{quote.get_status_display()}* — "
                    f"phải **đã duyệt** mới soạn hợp đồng được.")
        ct = Contract.objects.create(
            customer=quote.customer, quote=quote, owner=user,
            code=_next_contract_code(), value_vnd=quote.total_vnd,
            title=f"Hợp đồng theo báo giá {quote.code}",
        )
        return (f"✅ Đã soạn **hợp đồng nháp {ct.code}** cho **{quote.customer.name}** "
                f"từ báo giá {quote.code}, giá trị **{_vnd(ct.value_vnd)}**.\n"
                f"Vào màn Hợp đồng để bổ sung điều khoản & trình duyệt.")

    # Tạo trực tiếp cho 1 KH (chưa có giá trị)
    if not customer_name:
        return ("Cần **mã báo giá đã duyệt** (VD: BG-0007) hoặc **tên khách hàng** "
                "để soạn hợp đồng. VD: \"soạn hợp đồng từ báo giá BG-0007\".")
    cust = _resolve_customer(customer_name, user)
    if not cust:
        return f"Không tìm thấy khách hàng khớp \"{customer_name}\" (trong phạm vi của bạn)."
    ct = Contract.objects.create(customer=cust, owner=user, code=_next_contract_code(),
                                 title=f"Hợp đồng — {cust.name}")
    return (f"✅ Đã soạn **hợp đồng nháp {ct.code}** cho **{cust.name}** (chưa có giá trị).\n"
            f"Vào màn Hợp đồng để nhập giá trị, điều khoản & trình duyệt.")


# ── Tool ghi: phiếu nhập / xuất kho ─────────────────────────────────────────
def _default_warehouse():
    from apps.wms.models import Warehouse
    actives = Warehouse.objects.filter(is_active=True)
    if actives.count() == 1:
        return actives.first()
    return actives.filter(is_default=True).first()   # None nếu nhiều kho, không default


def _next_wms_code(model, prefix: str) -> str:
    """Sinh mã PREFIX-YYYY-NNN tăng dần trong năm."""
    year = date.today().year
    pre = f"{prefix}-{year}-"
    last = model.objects.filter(code__startswith=pre).order_by('-code').first()
    n = (int(last.code.rsplit('-', 1)[-1]) + 1) if last else 1
    return f"{pre}{n:03d}"


def _resolve_part_lines(items: list[dict]):
    """[{part_no, qty}] → (found[(pn,name,qty,Part)], missing[pn])."""
    from apps.catalog.models import Part
    found, missing = [], []
    for it in items or []:
        pn = str(it.get('part_no', '')).strip()
        qty = max(1, int(it.get('qty', 1) or 1))
        if not pn:
            continue
        part = Part.objects.filter(tokin_part_no=pn).first()
        if part:
            found.append((pn, part.display_name_vi or pn, qty, part))
        else:
            missing.append(pn)
    return found, missing


def tool_wms_inbound(user, items: list[dict]) -> str:
    """Lập PHIẾU NHẬP KHO nháp (draft). Nhận hàng thực hiện sau ở màn Nhập kho."""
    from apps.wms.models import InboundLine, InboundOrder
    wh = _default_warehouse()
    if not wh:
        return "Hệ thống có nhiều kho — vui lòng lập phiếu nhập trên màn Nhập kho và chọn kho cụ thể."
    if not items:
        return "Cần mã phụ tùng + số lượng để lập phiếu nhập. VD: \"nhập kho 100 x 001002\"."
    found, missing = _resolve_part_lines(items)
    if not found:
        return f"Không lập được phiếu nhập: không có mã phụ tùng hợp lệ ({', '.join(missing)})."
    order = InboundOrder.objects.create(code=_next_wms_code(InboundOrder, 'IN'),
                                        warehouse=wh, created_by=user, updated_by=user)
    for _pn, _n, qty, part in found:
        InboundLine.objects.create(inbound=order, part=part, qty_expected=qty)
    rows = '\n'.join(f"• {n} (`{pn}`) × {qty}" for pn, n, qty, _ in found)
    note = f"\n⚠️ Không thấy mã: {', '.join(missing)}" if missing else ""
    return (f"✅ Đã lập **phiếu nhập kho nháp {order.code}** (kho {wh.code}):\n{rows}{note}\n"
            f"Vào màn Nhập kho để xác nhận nhận hàng (cộng tồn).")


def tool_wms_outbound(user, items: list[dict], customer_name: str = '') -> str:
    """Lập PHIẾU XUẤT KHO nháp (draft). Soạn & giao hàng thực hiện sau ở màn Xuất kho."""
    from apps.wms.models import OutboundLine, OutboundOrder
    wh = _default_warehouse()
    if not wh:
        return "Hệ thống có nhiều kho — vui lòng lập phiếu xuất trên màn Xuất kho và chọn kho cụ thể."
    if not items:
        return "Cần mã phụ tùng + số lượng để lập phiếu xuất. VD: \"xuất kho 20 x 001002\"."
    found, missing = _resolve_part_lines(items)
    if not found:
        return f"Không lập được phiếu xuất: không có mã phụ tùng hợp lệ ({', '.join(missing)})."
    cust = _resolve_customer(customer_name, user) if customer_name else None
    order = OutboundOrder.objects.create(code=_next_wms_code(OutboundOrder, 'OUT'),
                                         warehouse=wh, customer=cust,
                                         created_by=user, updated_by=user)
    for _pn, _n, qty, part in found:
        OutboundLine.objects.create(outbound=order, part=part, qty_ordered=qty)
    rows = '\n'.join(f"• {n} (`{pn}`) × {qty}" for pn, n, qty, _ in found)
    who = f" cho **{cust.name}**" if cust else ""
    note = f"\n⚠️ Không thấy mã: {', '.join(missing)}" if missing else ""
    return (f"✅ Đã lập **phiếu xuất kho nháp {order.code}** (kho {wh.code}){who}:\n{rows}{note}\n"
            f"Vào màn Xuất kho để soạn hàng (pick) & giao.")


# ── Tool đọc: tra cứu tài liệu/sản phẩm Tokin (catalog) ─────────────────────
def tool_lookup_doc(question: str) -> str:
    """Tra cứu phụ tùng/súng hàn Tokin từ catalog (mã hoặc tên). Đọc DB thật."""
    from apps.catalog.models import Part

    codes = re.findall(r'\b[0-9]{4,}[A-Za-z0-9\-]*\b', question)
    part = None
    for cpn in codes:
        part = Part.objects.filter(tokin_part_no=cpn).first()
        if part:
            break
    if not part:
        # tìm theo tên: lấy cụm chữ có nghĩa cuối câu
        kw = re.sub(r'(tra cứu|tìm|cho tôi|thông tin|tài liệu|sản phẩm|về|part|phụ tùng)', '',
                    question, flags=re.I).strip()
        if len(kw) >= 2:
            part = Part.objects.filter(display_name_vi__icontains=kw).first()
    if not part:
        return ("Không tìm thấy phụ tùng khớp. Cho mình **mã** (VD 001002) hoặc "
                "**tên** chính xác hơn nhé.")

    spec = []
    if part.wire_size_mm:  spec.append(f"dây {part.wire_size_mm}mm")
    if part.thread_type:   spec.append(f"ren {part.thread_type}")
    if part.material:      spec.append(part.material)
    spec_s = ", ".join(spec) or "—"
    price = _vnd(part.price_vnd) if part.price_vnd else "liên hệ"
    torches = part.applicable_torches or part.torch_models or []
    t_s = (", ".join(map(str, torches[:6])) + ("…" if len(torches) > 6 else "")) if torches else "—"
    return (f"**{part.display_name_vi}** (`{part.tokin_part_no}`)\n"
            f"• Nhóm: {part.category or '—'} | Spec: {spec_s}\n"
            f"• Giá: **{price}** / {part.price_unit}\n"
            f"• Dùng cho súng: {t_s}")


# ── Tool đọc sâu: đơn của KH, tồn của mã ────────────────────────────────────
def tool_customer_orders(user, customer_name: str) -> str:
    from apps.sales.models import SalesOrder
    if not customer_name:
        return "Cần tên khách hàng. VD: \"đơn của Công ty ABC\"."
    cust = _resolve_customer(customer_name, user)
    if not cust:
        return f"Không tìm thấy khách hàng \"{customer_name}\" (trong phạm vi của bạn)."
    rows = (SalesOrder.objects.filter(customer=cust).order_by('-issued_date')[:8])
    if not rows:
        return f"**{cust.name}** chưa có đơn hàng nào."
    lines = []
    for o in rows:
        debt = (o.total_vnd or 0) - (o.paid_vnd or 0)
        tail = f" — còn nợ {_vnd(debt)}" if debt > 0 else " — đã thanh toán"
        lines.append(f"• {o.code} ({o.get_status_display()}): {_vnd(o.total_vnd)}{tail}")
    return f"Đơn hàng của **{cust.name}** (gần nhất):\n" + "\n".join(lines)


def tool_stock_lookup(question: str) -> str:
    from apps.catalog.models import Part
    from apps.wms.models import InventoryItem
    codes = re.findall(r'\b[0-9]{4,}[A-Za-z0-9\-]*\b', question)
    part = next((Part.objects.filter(pk=c).first() for c in codes
                 if Part.objects.filter(pk=c).exists()), None)
    if not part:
        return "Cho mình **mã phụ tùng** để tra tồn. VD: \"tồn 001002\"."
    rows = (InventoryItem.objects.filter(part=part)
            .select_related('bin', 'bin__zone__warehouse')[:20])
    total = sum(r.qty_on_hand for r in rows)
    if total == 0:
        return f"**{part.display_name_vi}** (`{part.tokin_part_no}`): hết hàng (tồn 0)."
    by = "\n".join(f"• {r.bin.full_code}: {r.qty_on_hand}" for r in rows if r.qty_on_hand)
    return f"Tồn **{part.display_name_vi}** (`{part.tokin_part_no}`): **{total}**\n{by}"


def answer(question: str, user) -> str:
    """Điểm vào chính: yêu cầu + user → trả lời/hành động (role-gated, data thật)."""
    from apps.accounts.roles import can_use_intent, role_of

    intent = _llm_intent(question) or _keyword_intent(question)
    name = intent.get('intent', 'unknown')
    role = role_of(user)

    # Gate role theo intent (trừ unknown — chỉ trả hướng dẫn)
    if name != 'unknown' and not can_use_intent(role, name):
        return (f"Xin lỗi, vai trò **{role}** không có quyền dùng chức năng này. "
                f"Liên hệ quản lý nếu cần.")

    if name == 'revenue':
        return tool_revenue(intent.get('period') or 'month')
    if name == 'customer_debt':
        cust_name = intent.get('customer_name') or _detect_customer(question)
        return tool_customer_debt(cust_name or None)
    if name == 'top_customers':
        return tool_top_customers()
    if name == 'dormant_customers':
        return tool_dormant_customers(int(intent.get('months') or 3))
    if name == 'ceo_report':
        return tool_ceo_report()
    if name == 'evaluate_plan':
        return tool_evaluate_plan()
    if name == 'create_lead':
        lead_name = (intent.get('lead_name') or '').strip()
        company = (intent.get('company') or '').strip()
        phone = (intent.get('phone') or '').strip() or _parse_phone(question)
        if not lead_name:
            # Fallback từ câu: bỏ từ khóa, lấy phần tên trước dấu phẩy.
            raw = re.sub(r'(tạo|tao|thêm|them|ghi)\s+lead|lead\s+mới|khách\s+tiềm\s+năng|khach\s+tiem\s+nang|ghi\s+lead',
                         '', question, flags=re.I)
            mcom = re.search(r'(?:công ty|cong ty|cty)\s+([\w\sÀ-ỹ.]+)', raw, re.I)
            if mcom and not company:
                company = mcom.group(1).split(',')[0].strip()
                raw = raw.replace(mcom.group(0), '')
            raw = re.sub(r'\b0\d{8,10}\b', '', raw.replace('.', ''))
            lead_name = raw.strip(' ,:-') or ''
        return tool_create_lead(user, lead_name, company, phone)
    if name == 'create_quote':
        cust_name = intent.get('customer_name') or _detect_customer(question)
        items = intent.get('items') or _parse_items(question)
        return tool_create_quote(user, cust_name, items)
    if name == 'create_contract':
        cust_name = intent.get('customer_name') or _detect_customer(question)
        m = re.search(r'\bBG[-\s]?(\d+)\b', question, re.I)
        quote_code = f"BG-{int(m.group(1)):04d}" if m else (intent.get('quote_code') or '')
        return tool_create_contract(user, cust_name, quote_code)
    if name == 'wms_inbound':
        items = intent.get('items') or _parse_items(question)
        return tool_wms_inbound(user, items)
    if name == 'wms_outbound':
        items = intent.get('items') or _parse_items(question)
        cust_name = intent.get('customer_name') or _detect_customer(question)
        return tool_wms_outbound(user, items, cust_name)
    if name == 'customer_orders':
        cust_name = intent.get('customer_name') or _detect_customer(question)
        return tool_customer_orders(user, cust_name)
    if name == 'stock_lookup':
        return tool_stock_lookup(question)
    if name == 'lookup_doc':
        return tool_lookup_doc(question)

    return ("Em là **trợ lý nội bộ Tokinarc**. Tùy quyền của anh/chị, em có thể: "
            "**làm báo giá** (VD: \"làm báo giá cho Công ty ABC: 5 x 001002\"), "
            "xem **doanh thu**/**công nợ**/**top khách hàng**, **báo cáo CEO**, "
            "**đánh giá kế hoạch** (pipeline). Anh/chị nói rõ yêu cầu nhé.")


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
    hd = m.get('hoat_dong')
    if hd:
        wh = hd.get('hoat_dong_kho', {})
        lines += [
            "",
            "**Hoạt động nổi bật** (30 ngày)",
            f"• Sales: {hd['so_cuoc_gap']} cuộc gặp ({hd['cuoc_gap_co_ghi_am']} có ghi âm), "
            f"{hd['so_cuoc_goi_email']} cuộc gọi/email ({hd['goi_email_co_ghi_am']} có ghi âm).",
        ]
        for r in hd.get('recap_cuoc_gap', [])[:5]:
            tail = f" → {r['viec_tiep']}" if r['viec_tiep'] else ""
            mic = " 🎙" if r['co_ghi_am'] else ""
            lines.append(f"  - {r['kh']} ({r['ngay']}){mic}: {r['recap']}{tail}")
        lines.append(
            f"• Kho: {wh.get('phieu_nhap', 0)} lượt nhập, {wh.get('phieu_xuat', 0)} lượt xuất, "
            f"{wh.get('dieu_chinh_ton', 0)} điều chỉnh tồn"
            + (f", {wh['kiem_ke']} phiên kiểm kê." if 'kiem_ke' in wh else "."))
    return "\n".join(lines)


def _llm_summary(m: dict) -> str | None:
    """Nhờ Gemini viết tóm tắt điều hành từ metrics thật (không bịa số)."""
    key = _gemini_key()
    if not key:
        return None
    model = _gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    prompt = (
        "Bạn là trợ lý điều hành. Dưới đây là DỮ LIỆU THẬT của công ty phân phối súng hàn "
        "Tokinarc theo từng phòng ban: phần SỐ LIỆU (VND) và phần 'hoat_dong' gồm RECAP các "
        "cuộc gặp/gọi khách gần đây + hoạt động kho. Hãy viết bản TÓM TẮT ĐIỀU HÀNH bằng "
        "tiếng Việt cho Giám đốc, gồm 5 mục in đậm: **Tổng quan**, **Điểm tích cực**, "
        "**Cần chú ý**, **Hoạt động nổi bật**, **Khuyến nghị tuần này**.\n"
        "- Mục 'Hoạt động nổi bật': tóm tắt NỘI DUNG các cuộc gặp/gọi (khách nói gì, nhu cầu, "
        "phàn nàn, việc cần follow-up) dựa trên recap, nêu rõ tên khách; nêu hoạt động kho "
        "(nhập/xuất/kiểm kê/điều chỉnh) và số cuộc CÓ GHI ÂM.\n"
        "CHỈ dùng đúng dữ liệu cho sẵn, KHÔNG bịa số/nội dung. Súc tích.\n\nDỮ LIỆU:\n"
        + json.dumps(m, ensure_ascii=False)
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


def _gather_activities(days: int = 30, max_items: int = 12) -> dict:
    """Gom HOẠT ĐỘNG gần đây: recap cuộc gặp/gọi + đếm ghi âm + hoạt động kho."""
    from datetime import timedelta

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


def executive_summary() -> dict:
    """Tóm tắt toàn bộ hoạt động phòng ban. Số liệu thật, lời do LLM (fallback template)."""
    m = _gather_metrics()
    m['hoat_dong'] = _gather_activities()
    ai = _llm_summary(m)
    return {
        'summary': ai or _template_summary(m),
        'metrics': m,
        'generated_by': 'ai' if ai else 'template',
    }
