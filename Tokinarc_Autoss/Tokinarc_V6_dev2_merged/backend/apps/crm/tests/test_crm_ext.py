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
    # sale tạo quote
    sc = APIClient(); sc.force_authenticate(sale)
    q = sc.post('/api/v1/crm/quotes/', {'customer': str(cust.id),
                'lines': [{'part_no': 'X', 'qty': 2, 'unit_price_vnd': 5000}]},
                format='json').data
    # manager approve
    mc = APIClient(); mc.force_authenticate(manager)
    ra = mc.post(f"/api/v1/crm/quotes/{q['id']}/approve/")
    assert ra.status_code == 200
    assert ra.data['status'] == 'approved'
    # to-contract
    rc = mc.post(f"/api/v1/crm/quotes/{q['id']}/to-contract/")
    assert rc.status_code == 200
    assert rc.data['contract_order_code'].startswith('HD-')


@pytest.mark.django_db
def test_to_contract_requires_approved(api, sale):
    cust = CustomerFactory(owner=sale)
    q = api.post('/api/v1/crm/quotes/', {'customer': str(cust.id),
                 'lines': [{'part_no': 'X', 'qty': 1, 'unit_price_vnd': 100}]},
                 format='json').data
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
