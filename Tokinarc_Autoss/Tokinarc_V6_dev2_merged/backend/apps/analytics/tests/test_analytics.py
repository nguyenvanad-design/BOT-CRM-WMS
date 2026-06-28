"""
Tokinarc V6.C — apps/analytics/tests/test_analytics.py
"""
from __future__ import annotations

import datetime as dt

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.models import Customer
from apps.sales.models import SalesOrder


@pytest.fixture
def manager(db):
    return User.objects.create(username='mgr', role=Role.MANAGER)


@pytest.fixture
def sale(db):
    return User.objects.create(username='s1', role=Role.SALES)


@pytest.fixture
def seeded(db, sale):
    cust = Customer.objects.create(code='KH-9001', name='ACME', segment='factory', owner=sale)
    SalesOrder.objects.create(code='HD-9001', customer=cust, issued_date=dt.date(2026, 6, 1),
                              total_vnd=1000000, paid_vnd=600000, status='active', owner=sale)
    SalesOrder.objects.create(code='HD-9002', customer=cust, issued_date=dt.date(2026, 6, 10),
                              total_vnd=2000000, paid_vnd=2000000, status='completed', owner=sale)
    return cust


@pytest.mark.django_db
def test_kpi_overview(manager, seeded):
    c = APIClient(); c.force_authenticate(manager)
    r = c.get('/api/v1/analytics/kpi/overview/')
    assert r.status_code == 200
    assert r.data['revenue_vnd'] == 3000000
    assert r.data['debt_vnd'] == 400000


@pytest.mark.django_db
def test_revenue_by_segment(manager, seeded):
    c = APIClient(); c.force_authenticate(manager)
    r = c.get('/api/v1/analytics/revenue/by-segment/')
    assert r.status_code == 200
    assert r.data[0]['segment'] == 'factory'
    assert r.data[0]['revenue_vnd'] == 3000000


@pytest.mark.django_db
def test_sales_role_blocked(sale, seeded):
    c = APIClient(); c.force_authenticate(sale)
    assert c.get('/api/v1/analytics/kpi/overview/').status_code == 403


@pytest.mark.django_db
def test_debt_aging(manager, seeded):
    c = APIClient(); c.force_authenticate(manager)
    r = c.get('/api/v1/analytics/debt-aging/')
    assert r.status_code == 200
    # chỉ HD-9001 còn nợ
    assert r.data['count'] == 1


# ─── Bot nội bộ (assistant) — tích hợp CRM theo role ────────────────────────
@pytest.fixture
def no_llm(monkeypatch):
    """Tắt gọi Gemini thật trong test → ép dùng keyword/template."""
    from apps.analytics import assistant
    monkeypatch.setattr(assistant, '_gemini_key', lambda: '')


@pytest.fixture
def customer(db):
    return User.objects.create(username='kh1', role=Role.CUSTOMER)


@pytest.fixture
def ceo(db):
    return User.objects.create(username='ceo1', role=Role.CEO)


@pytest.mark.django_db
def test_assistant_customer_blocked(customer):
    """Khách hàng KHÔNG vào được bot nội bộ (permission)."""
    c = APIClient(); c.force_authenticate(customer)
    r = c.post('/api/v1/analytics/assistant/query/', {'query': 'doanh thu tháng này'}, format='json')
    assert r.status_code == 403


@pytest.mark.django_db
def test_assistant_sale_create_quote(sale, seeded, no_llm):
    """Sale nhờ bot làm báo giá → tạo Quote nháp THẬT, owner = sale, giá từ catalog."""
    from apps.catalog.models import Part
    from apps.crm.models import Quote
    Part.objects.create(tokin_part_no='001002', category='tip',
                        display_name_vi='Bép hàn 0.8', price_vnd=120000)

    from apps.analytics.assistant import tool_create_quote
    c = APIClient(); c.force_authenticate(sale)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'làm báo giá cho ACME: 2 x 001002'}, format='json')
    assert r.status_code == 200
    # Thiết kế mới: XEM TRƯỚC trước, CHƯA ghi.
    assert 'xem trước' in r.data['text'].lower()
    assert Quote.objects.filter(owner=sale).count() == 0

    # Xác nhận (confirm=True) → ghi thật.
    tool_create_quote(sale, 'ACME', [{'part_no': '001002', 'qty': 2}], confirm=True)
    q = Quote.objects.get(owner=sale)
    assert q.status == 'draft'
    assert q.customer.name == 'ACME'
    assert int(q.total_vnd) == 240000   # 2 × 120.000
    assert q.lines.count() == 1


@pytest.mark.django_db
def test_assistant_sale_create_lead(sale, no_llm):
    """Sale nhờ bot tạo lead → ghi Lead THẬT vào CRM, owner = sale."""
    from apps.analytics.assistant import tool_create_lead
    from apps.crm.models import Lead
    c = APIClient(); c.force_authenticate(sale)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'tạo lead Nguyễn Văn A, công ty ABC, 0901234567'}, format='json')
    assert r.status_code == 200
    assert 'xem trước' in r.data['text'].lower()        # XEM TRƯỚC, chưa ghi
    assert Lead.objects.filter(owner=sale).count() == 0
    # Xác nhận → ghi thật.
    tool_create_lead(sale, 'Nguyễn Văn A', 'ABC', '0901234567', confirm=True)
    lead = Lead.objects.get(owner=sale)
    assert lead.name == 'Nguyễn Văn A'
    assert lead.company == 'ABC'
    assert lead.phone == '0901234567'
    assert lead.source == 'chatbot'


@pytest.mark.django_db
def test_assistant_warehouse_blocked_create_lead(warehouse_user, no_llm):
    """NV kho KHÔNG được tạo lead (ngoài phạm vi) → từ chối, không tạo Lead."""
    from apps.crm.models import Lead
    c = APIClient(); c.force_authenticate(warehouse_user)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'tạo lead Trần B 0912345678'}, format='json')
    assert r.status_code == 200
    assert Lead.objects.count() == 0


@pytest.mark.django_db
def test_assistant_sale_blocked_ceo_report(sale, seeded, no_llm):
    """Sale KHÔNG được dùng báo cáo CEO → trả thông báo từ chối (không 403)."""
    c = APIClient(); c.force_authenticate(sale)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'cho tôi báo cáo CEO'}, format='json')
    assert r.status_code == 200
    assert 'không có quyền' in r.data['text'].lower()


@pytest.mark.django_db
def test_assistant_manager_ceo_report(manager, seeded, no_llm):
    """Manager xin báo cáo điều hành → có nội dung tóm tắt (số liệu thật)."""
    c = APIClient(); c.force_authenticate(manager)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'tóm tắt điều hành'}, format='json')
    assert r.status_code == 200
    assert 'Tổng quan' in r.data['text']


@pytest.mark.django_db
def test_assistant_manager_evaluate_plan(manager, seeded, no_llm):
    """Manager đánh giá kế hoạch (pipeline) → không lỗi, có tiêu đề đánh giá."""
    c = APIClient(); c.force_authenticate(manager)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'đánh giá kế hoạch pipeline'}, format='json')
    assert r.status_code == 200
    assert 'kế hoạch' in r.data['text'].lower()


@pytest.mark.django_db
def test_assistant_create_contract_from_approved_quote(sale, seeded, no_llm):
    """Sale soạn hợp đồng từ báo giá ĐÃ DUYỆT → tạo Contract nháp THẬT."""
    from apps.crm.models import Contract, Quote, QuoteStatus
    q = Quote.objects.create(code='BG-0007', customer=seeded, owner=sale,
                             total_vnd=5_000_000, status=QuoteStatus.APPROVED)
    from apps.analytics.assistant import tool_create_contract
    c = APIClient(); c.force_authenticate(sale)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'soạn hợp đồng từ báo giá BG-0007'}, format='json')
    assert r.status_code == 200
    assert 'xem trước' in r.data['text'].lower()        # XEM TRƯỚC, chưa ghi
    assert Contract.objects.filter(quote=q).count() == 0
    # Xác nhận → ghi thật.
    tool_create_contract(sale, '', 'BG-0007', confirm=True)
    ct = Contract.objects.get(quote=q)
    assert ct.status == 'draft'
    assert int(ct.value_vnd) == 5_000_000
    assert ct.owner == sale


@pytest.fixture
def warehouse_user(db):
    return User.objects.create(username='kho1', role=Role.WAREHOUSE)


@pytest.fixture
def wh(db):
    from apps.wms.models import Warehouse
    return Warehouse.objects.create(code='HCM', name='Kho HCM', is_active=True, is_default=True)


@pytest.fixture
def part1(db):
    from apps.catalog.models import Part
    return Part.objects.create(tokin_part_no='001002', category='tip',
                               display_name_vi='Bép hàn 0.8', price_vnd=120000)


@pytest.mark.django_db
def test_assistant_warehouse_inbound(warehouse_user, wh, part1, no_llm):
    """Nhân viên kho lập phiếu NHẬP kho qua bot → tạo InboundOrder nháp THẬT."""
    from apps.analytics.assistant import tool_wms_inbound
    from apps.wms.models import InboundOrder
    c = APIClient(); c.force_authenticate(warehouse_user)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'nhập kho 100 x 001002'}, format='json')
    assert r.status_code == 200
    assert 'xem trước' in r.data['text'].lower()        # XEM TRƯỚC, chưa ghi
    assert InboundOrder.objects.count() == 0
    # Xác nhận → ghi thật.
    tool_wms_inbound(warehouse_user, [{'part_no': '001002', 'qty': 100}], confirm=True)
    o = InboundOrder.objects.get()
    assert o.status == 'draft' and o.warehouse == wh
    assert o.lines.count() == 1 and o.lines.first().qty_expected == 100


@pytest.mark.django_db
def test_assistant_warehouse_outbound(warehouse_user, wh, part1, no_llm):
    """Nhân viên kho lập phiếu XUẤT kho qua bot → tạo OutboundOrder nháp THẬT."""
    from apps.analytics.assistant import tool_wms_outbound
    from apps.wms.models import OutboundOrder
    c = APIClient(); c.force_authenticate(warehouse_user)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'xuất kho 20 x 001002'}, format='json')
    assert r.status_code == 200
    assert 'xem trước' in r.data['text'].lower()        # XEM TRƯỚC, chưa ghi
    assert OutboundOrder.objects.count() == 0
    # Xác nhận → ghi thật.
    tool_wms_outbound(warehouse_user, [{'part_no': '001002', 'qty': 20}], confirm=True)
    o = OutboundOrder.objects.get()
    assert o.status == 'draft'
    assert o.lines.first().qty_ordered == 20


@pytest.mark.django_db
def test_assistant_customer_orders(sale, seeded, no_llm):
    """Sale hỏi 'đơn của ACME' → liệt kê đơn (seeded có HD-9001/9002)."""
    c = APIClient(); c.force_authenticate(sale)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'đơn của ACME'}, format='json')
    assert r.status_code == 200
    assert 'HD-9001' in r.data['text']


@pytest.mark.django_db
def test_assistant_stock_lookup(warehouse_user, part1, no_llm):
    """Nhân viên hỏi tồn 1 mã → trả tổng tồn + theo ô."""
    from apps.wms.models import Bin, InventoryItem, Warehouse, Zone
    wh = Warehouse.objects.create(code='HCM', name='Kho', is_active=True, is_default=True)
    z = Zone.objects.create(warehouse=wh, code='A', name='A')
    b = Bin.objects.create(zone=z, rack='R01', bin_code='B01', full_code='HCM-A-R01-B01')
    InventoryItem.objects.create(bin=b, part=part1, qty_on_hand=42)
    c = APIClient(); c.force_authenticate(warehouse_user)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'tồn 001002'}, format='json')
    assert r.status_code == 200 and '42' in r.data['text']


@pytest.mark.django_db
def test_summary_export_xlsx(manager, seeded, no_llm):
    c = APIClient(); c.force_authenticate(manager)
    r = c.get('/api/v1/analytics/assistant/summary/export/')
    assert r.status_code == 200 and 'spreadsheet' in r['Content-Type']


@pytest.mark.django_db
def test_assistant_lookup_doc(warehouse_user, part1, no_llm):
    """Mọi nhân viên tra cứu phụ tùng Tokin → trả spec/giá từ catalog."""
    c = APIClient(); c.force_authenticate(warehouse_user)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'tra cứu phụ tùng 001002'}, format='json')
    assert r.status_code == 200
    assert 'Bép hàn 0.8' in r.data['text'] and '001002' in r.data['text']


@pytest.mark.django_db
def test_assistant_sale_blocked_wms(sale, wh, part1, no_llm):
    """Sale KHÔNG có quyền lập phiếu kho → từ chối."""
    c = APIClient(); c.force_authenticate(sale)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'nhập kho 5 x 001002'}, format='json')
    assert r.status_code == 200
    assert 'không có quyền' in r.data['text'].lower()


@pytest.mark.django_db
def test_assistant_manager_blocked_wms(manager, wh, part1, no_llm):
    """Manager KHÔNG lập phiếu kho qua bot (chỉ warehouse/CEO/admin)."""
    from apps.wms.models import InboundOrder
    c = APIClient(); c.force_authenticate(manager)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'nhập kho 5 x 001002'}, format='json')
    assert r.status_code == 200
    assert 'không có quyền' in r.data['text'].lower()
    assert not InboundOrder.objects.exists()


@pytest.mark.django_db
def test_assistant_ceo_can_do_everything(ceo, wh, part1, seeded, no_llm):
    """CEO toàn quyền: lập phiếu kho + báo cáo điều hành + làm báo giá."""
    c = APIClient(); c.force_authenticate(ceo)
    # Lệnh ghi → XEM TRƯỚC; đọc (báo cáo) → nội dung ngay.
    assert 'xem trước' in c.post('/api/v1/analytics/assistant/query/',
        {'query': 'nhập kho 5 x 001002'}, format='json').data['text'].lower()
    assert 'Tổng quan' in c.post('/api/v1/analytics/assistant/query/',
        {'query': 'báo cáo điều hành'}, format='json').data['text']
    assert 'xem trước' in c.post('/api/v1/analytics/assistant/query/',
        {'query': 'làm báo giá cho ACME: 2 x 001002'}, format='json').data['text'].lower()


@pytest.mark.django_db
def test_assistant_contract_blocked_if_quote_not_approved(sale, seeded, no_llm):
    """Báo giá chưa duyệt → không soạn được hợp đồng."""
    from apps.crm.models import Contract, Quote, QuoteStatus
    Quote.objects.create(code='BG-0008', customer=seeded, owner=sale,
                         total_vnd=3_000_000, status=QuoteStatus.DRAFT)
    c = APIClient(); c.force_authenticate(sale)
    r = c.post('/api/v1/analytics/assistant/query/',
               {'query': 'soạn hợp đồng từ báo giá BG-0008'}, format='json')
    assert r.status_code == 200
    assert 'phải' in r.data['text'].lower() and 'duyệt' in r.data['text'].lower()
    assert not Contract.objects.filter(quote__code='BG-0008').exists()
