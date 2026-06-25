"""
Tokinarc V6.C-fix3 — apps/crm/tests/test_crm_ext.py

Test CRM mở rộng: Lead, Opportunity, Quote, Visit, Ticket.
Cover các endpoint mà chatbot/tool_clients.py gọi (trước đó 404):
  - create_quote (total tính ở server từ lines)
  - approve_quote (chặn self-approve, chỉ manager+)
  - quote_to_contract (chỉ khi approved)
  - move_opportunity_stage
  - create_visit, create_ticket
  - ownership filter (sale chỉ thấy của mình)
"""
from __future__ import annotations

import factory
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.crm.models import Customer, Opportunity, Quote

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
    username = factory.Sequence(lambda n: f'extuser{n}')
    role     = 'sales'


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer
    code  = factory.Sequence(lambda n: f'KHX-{n:04d}')
    name  = factory.Sequence(lambda n: f'Cong ty {n}')
    owner = factory.SubFactory(UserFactory)


@pytest.fixture
def sale(db):
    return UserFactory(role='sales')


@pytest.fixture
def manager(db):
    return UserFactory(role='manager')


@pytest.fixture
def ceo(db):
    return UserFactory(role='ceo')


@pytest.fixture
def api(sale):
    c = APIClient(); c.force_authenticate(sale); return c


# ─── Lead ────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_lead(api):
    r = api.post('/api/v1/crm/leads/', {'name': 'Anh Tuan', 'company': 'Steel Co',
                                        'source': 'zalo'}, format='json')
    assert r.status_code == 201
    assert r.data['status'] == 'new'


@pytest.mark.django_db
def test_lead_convert_creates_customer(api):
    lead = api.post('/api/v1/crm/leads/', {'name': 'KH moi'}, format='json').data
    r = api.post(f"/api/v1/crm/leads/{lead['id']}/convert/")
    assert r.status_code == 200
    assert r.data['customer_code'].startswith('KH-')


@pytest.mark.django_db
def test_lead_convert_carries_phone_into_contact(api):
    """Convert phải mang SĐT/email/ghi chú sang KH (tạo Contact chính)."""
    from apps.crm.models import Contact, Customer
    lead = api.post('/api/v1/crm/leads/',
                    {'name': 'Mr. Văn', 'phone': '0918461177',
                     'email': 'van@abc.vn', 'notes': 'tvr mua 20 tip'},
                    format='json').data
    r = api.post(f"/api/v1/crm/leads/{lead['id']}/convert/")
    assert r.status_code == 200
    cust = Customer.objects.get(code=r.data['customer_code'])
    assert cust.notes == 'tvr mua 20 tip'
    ct = Contact.objects.get(customer=cust)
    assert ct.full_name == 'Mr. Văn' and ct.phone == '0918461177'
    assert ct.email == 'van@abc.vn' and ct.is_primary is True


# ─── Opportunity ─────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_and_move_opportunity(api, sale):
    cust = CustomerFactory(owner=sale)
    opp = api.post('/api/v1/crm/opportunities/',
                   {'customer': str(cust.id), 'title': 'Deal 100tr',
                    'est_value_vnd': 100000000}, format='json').data
    assert opp['stage'] == 'prospect'
    r = api.post(f"/api/v1/crm/opportunities/{opp['id']}/move-stage/",
                 {'stage': 'proposal'}, format='json')
    assert r.status_code == 200
    assert r.data['stage'] == 'proposal'


@pytest.mark.django_db
def test_move_opportunity_invalid_stage(api, sale):
    cust = CustomerFactory(owner=sale)
    opp = Opportunity.objects.create(customer=cust, title='X', owner=sale)
    r = api.post(f"/api/v1/crm/opportunities/{opp.id}/move-stage/",
                 {'stage': 'bogus'}, format='json')
    assert r.status_code == 400


# ─── Quote ───────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_quote_total_computed_server(api, sale):
    """total_vnd phải tính từ lines ở server, KHÔNG tin client."""
    cust = CustomerFactory(owner=sale)
    payload = {
        'customer': str(cust.id),
        'total_vnd': 999,   # client cố set bậy → phải bị bỏ qua
        'lines': [
            {'part_no': '002001', 'qty': 50, 'unit_price_vnd': 12000},
            {'part_no': '001002', 'qty': 20, 'unit_price_vnd': 30000},
        ],
    }
    r = api.post('/api/v1/crm/quotes/', payload, format='json')
    assert r.status_code == 201
    # 50*12000 + 20*30000 = 600000 + 600000 = 1,200,000
    assert int(r.data['total_vnd']) == 1_200_000
    assert r.data['code'].startswith('BG-')


@pytest.mark.django_db
def test_approve_quote_blocks_self_approve(api, sale):
    """Sale tạo quote rồi tự approve → 403 (sale không phải manager)."""
    cust = CustomerFactory(owner=sale)
    q = api.post('/api/v1/crm/quotes/', {'customer': str(cust.id),
                 'lines': [{'part_no': 'X', 'qty': 1, 'unit_price_vnd': 100}]},
                 format='json').data
    r = api.post(f"/api/v1/crm/quotes/{q['id']}/approve/")
    assert r.status_code == 403


@pytest.mark.django_db
def test_manager_approve_then_to_contract(manager, sale):
    cust = CustomerFactory(owner=sale)
    # sale tạo quote CK 8% (>5% → cần manager duyệt, không tự duyệt)
    sc = APIClient(); sc.force_authenticate(sale)
    q = sc.post('/api/v1/crm/quotes/', {'customer': str(cust.id), 'discount_pct': 8,
                'lines': [{'part_no': 'X', 'qty': 2, 'unit_price_vnd': 5000}]},
                format='json').data
    assert q['status'] == 'draft'
    # manager approve
    mc = APIClient(); mc.force_authenticate(manager)
    ra = mc.post(f"/api/v1/crm/quotes/{q['id']}/approve/")
    assert ra.status_code == 200
    assert ra.data['status'] == 'approved'
    # to-contract
    rc = mc.post(f"/api/v1/crm/quotes/{q['id']}/to-contract/")
    assert rc.status_code == 200
    assert rc.data['contract_order_code'].startswith('HD-')


# ─── Duyệt theo % CHIẾT KHẤU (sale ≤5% tự duyệt · manager ≤10% · CEO >10%) ──
def _make_quote(sale, cust, unit_price, qty=1, discount_pct=0):
    sc = APIClient(); sc.force_authenticate(sale)
    return sc.post('/api/v1/crm/quotes/', {'customer': str(cust.id), 'discount_pct': discount_pct,
                   'lines': [{'part_no': 'X', 'qty': qty, 'unit_price_vnd': unit_price}]},
                   format='json').data


@pytest.mark.django_db
def test_quote_over_threshold_needs_ceo(manager, ceo, sale):
    """Chiết khấu > 10%: manager duyệt → pending_ceo, chưa được to-contract."""
    cust = CustomerFactory(owner=sale)
    q = _make_quote(sale, cust, unit_price=10_000_000, discount_pct=15)   # CK 15% > 10%
    assert q['requires_l2'] is True
    assert q['status'] == 'draft'   # >5% nên KHÔNG tự duyệt

    mc = APIClient(); mc.force_authenticate(manager)
    r1 = mc.post(f"/api/v1/crm/quotes/{q['id']}/approve/")
    assert r1.status_code == 200
    assert r1.data['status'] == 'pending_ceo'
    # chưa duyệt cấp 2 → không tạo HĐ được
    assert mc.post(f"/api/v1/crm/quotes/{q['id']}/to-contract/").status_code == 400

    # CEO duyệt cấp 2 → approved → tạo HĐ
    cc = APIClient(); cc.force_authenticate(ceo)
    r2 = cc.post(f"/api/v1/crm/quotes/{q['id']}/approve-l2/")
    assert r2.status_code == 200
    assert r2.data['status'] == 'approved'
    assert r2.data['l1_approved_by'] is not None and r2.data['l2_approved_by'] is not None
    assert cc.post(f"/api/v1/crm/quotes/{q['id']}/to-contract/").status_code == 200


@pytest.mark.django_db
def test_quote_under_threshold_skips_ceo(manager, sale):
    """Chiết khấu 5-10%: manager duyệt → approved luôn (không cần CEO)."""
    cust = CustomerFactory(owner=sale)
    q = _make_quote(sale, cust, unit_price=5_000_000, discount_pct=8)   # 5<CK≤10
    assert q['requires_l2'] is False
    assert q['status'] == 'draft'
    mc = APIClient(); mc.force_authenticate(manager)
    r = mc.post(f"/api/v1/crm/quotes/{q['id']}/approve/")
    assert r.status_code == 200
    assert r.data['status'] == 'approved'


@pytest.mark.django_db
def test_quote_within_sale_authority_auto_approved(sale):
    """Chiết khấu ≤5%: tự động duyệt ngay khi tạo (quyền sale)."""
    cust = CustomerFactory(owner=sale)
    q = _make_quote(sale, cust, unit_price=5_000_000, discount_pct=3)
    assert q['status'] == 'approved'
    assert q['requires_l2'] is False


@pytest.mark.django_db
def test_manager_cannot_approve_l2(manager, sale):
    """Manager (cấp 1) không được duyệt cấp 2 → 403."""
    cust = CustomerFactory(owner=sale)
    q = _make_quote(sale, cust, unit_price=10_000_000, discount_pct=15)
    mc = APIClient(); mc.force_authenticate(manager)
    mc.post(f"/api/v1/crm/quotes/{q['id']}/approve/")   # → pending_ceo
    r = mc.post(f"/api/v1/crm/quotes/{q['id']}/approve-l2/")
    assert r.status_code == 403


@pytest.mark.django_db
def test_ceo_cannot_l2_own_l1(ceo, sale):
    """CEO tự duyệt cấp 1 rồi cấp 2 cùng báo giá → cấp 2 bị chặn (4-eyes)."""
    cust = CustomerFactory(owner=sale)
    q = _make_quote(sale, cust, unit_price=10_000_000, discount_pct=15)
    cc = APIClient(); cc.force_authenticate(ceo)
    assert cc.post(f"/api/v1/crm/quotes/{q['id']}/approve/").data['status'] == 'pending_ceo'
    r = cc.post(f"/api/v1/crm/quotes/{q['id']}/approve-l2/")
    assert r.status_code == 403


@pytest.mark.django_db
def test_to_contract_requires_approved(api, sale):
    cust = CustomerFactory(owner=sale)
    q = api.post('/api/v1/crm/quotes/', {'customer': str(cust.id), 'discount_pct': 8,
                 'lines': [{'part_no': 'X', 'qty': 1, 'unit_price_vnd': 1000}]},
                 format='json').data
    assert q['status'] == 'draft'   # CK 8% > 5% → cần duyệt, chưa approved
    r = api.post(f"/api/v1/crm/quotes/{q['id']}/to-contract/")
    assert r.status_code == 400   # chưa approved


# ─── Visit ───────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_visit(api, sale):
    cust = CustomerFactory(owner=sale)
    r = api.post('/api/v1/crm/visits/', {'customer': str(cust.id),
                 'visit_date': '2026-06-17', 'purpose': 'Demo sản phẩm'},
                 format='json')
    assert r.status_code == 201


# ─── Ticket ──────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_ticket(api, sale):
    cust = CustomerFactory(owner=sale)
    r = api.post('/api/v1/crm/tickets/', {'customer': str(cust.id),
                 'title': 'Máy hàn lỗi', 'priority': 'high'}, format='json')
    assert r.status_code == 201
    assert r.data['code'].startswith('TK-')


# ─── Ownership ───────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_sale_sees_only_own_quotes(sale):
    other = UserFactory(role='sales')
    c1 = CustomerFactory(owner=sale)
    c2 = CustomerFactory(owner=other)
    Quote.objects.create(code='BG-9001', customer=c1, owner=sale)
    Quote.objects.create(code='BG-9002', customer=c2, owner=other)
    cli = APIClient(); cli.force_authenticate(sale)
    r = cli.get('/api/v1/crm/quotes/')
    codes = [q['code'] for q in r.data['results']] if 'results' in r.data else [q['code'] for q in r.data]
    assert 'BG-9001' in codes
    assert 'BG-9002' not in codes


@pytest.mark.django_db
def test_unauthenticated_blocked(db):
    c = APIClient()
    r = c.post('/api/v1/crm/quotes/', {}, format='json')
    assert r.status_code in (401, 403)


# ─── N1.1 Quote → SalesOrder ─────────────────────────────────────────────
@pytest.mark.django_db
def test_quote_to_order_creates_salesorder(sale):
    from apps.crm.models import Quote, QuoteLine, QuoteStatus
    from apps.sales.models import SalesOrder
    cust = CustomerFactory(owner=sale)
    q = Quote.objects.create(code='BG-7001', customer=cust, owner=sale,
                             status=QuoteStatus.APPROVED)
    QuoteLine.objects.create(quote=q, part_no='X1', part_name='Part X', qty=3, unit_price_vnd=10000)
    q.recompute_total(); q.save(update_fields=['total_vnd'])
    cli = APIClient(); cli.force_authenticate(sale)
    r = cli.post(f'/api/v1/crm/quotes/{q.id}/to-order/')
    assert r.status_code == 200
    order = SalesOrder.objects.get(code=r.data['order_code'])
    assert order.customer_id == cust.id and int(order.total_vnd) == 30000
    assert order.lines.count() == 1
    q.refresh_from_db(); assert q.status == 'converted'


# ─── N2.5 Reject quote ───────────────────────────────────────────────────
@pytest.mark.django_db
def test_notification_on_pending_ceo(manager, ceo, sale):
    """Báo giá CK >10% → manager duyệt cấp 1 → CEO nhận thông báo."""
    from apps.common.models import Notification
    cust = CustomerFactory(owner=sale)
    q = _make_quote(sale, cust, unit_price=10_000_000, discount_pct=15)
    mc = APIClient(); mc.force_authenticate(manager)
    mc.post(f"/api/v1/crm/quotes/{q['id']}/approve/")
    assert Notification.objects.filter(user=ceo, kind='quote_approval', is_read=False).exists()
    # CEO xem được qua API
    cc = APIClient(); cc.force_authenticate(ceo)
    assert cc.get('/api/v1/notifications/unread/').data['count'] >= 1


@pytest.mark.django_db
def test_reject_quote_with_reason(manager, sale):
    from apps.crm.models import Quote, QuoteStatus
    cust = CustomerFactory(owner=sale)
    q = Quote.objects.create(code='BG-7101', customer=cust, owner=sale, status=QuoteStatus.SENT)
    mc = APIClient(); mc.force_authenticate(manager)
    r = mc.post(f'/api/v1/crm/quotes/{q.id}/reject/', {'reason': 'Giá cao'}, format='json')
    assert r.status_code == 200 and r.data['status'] == 'rejected'
    q.refresh_from_db(); assert 'Giá cao' in q.notes
    # sale không được reject
    sc = APIClient(); sc.force_authenticate(sale)
    q2 = Quote.objects.create(code='BG-7102', customer=cust, owner=sale, status=QuoteStatus.SENT)
    assert sc.post(f'/api/v1/crm/quotes/{q2.id}/reject/').status_code == 403


# ─── N2.7 CRM forecast ───────────────────────────────────────────────────
@pytest.mark.django_db
def test_crm_forecast_endpoint(sale):
    from apps.crm.models import Opportunity
    cust = CustomerFactory(owner=sale)
    Opportunity.objects.create(customer=cust, owner=sale, title='O1', stage='proposal',
                               est_value_vnd=100_000_000, probability=50)
    cli = APIClient(); cli.force_authenticate(sale)
    r = cli.get('/api/v1/crm/opportunities/forecast/')
    assert r.status_code == 200
    assert r.data['open_count'] == 1
    assert r.data['weighted_total'] == 50_000_000


# ─── N2.6 Expire contracts command ───────────────────────────────────────
@pytest.mark.django_db
def test_expire_contracts_command(sale):
    import datetime as dt
    from django.core.management import call_command
    from apps.crm.models import Contract, ContractStatus
    cust = CustomerFactory(owner=sale)
    c = Contract.objects.create(code='HD-EXP-1', customer=cust, owner=sale,
                                status=ContractStatus.ACTIVE, end_date=dt.date(2020, 1, 1))
    call_command('expire_contracts')
    c.refresh_from_db(); assert c.status == 'expired'
