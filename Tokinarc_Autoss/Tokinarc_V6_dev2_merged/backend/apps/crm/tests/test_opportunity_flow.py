"""Kanban TỰ ĐỘNG: deal tiến giai đoạn theo sự kiện thật (không kéo thả)
+ mark-lost bắt buộc lý do. Xem apps/crm/opportunity_flow.py."""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.models import Customer, Opportunity, OppStage


@pytest.fixture
def sale():
    return User.objects.create(username='of_sale', role=Role.SALES)


@pytest.fixture
def deal(sale):
    cust = Customer.objects.create(code='KH-OF1', name='OppFlow Co', owner=sale)
    opp = Opportunity.objects.create(customer=cust, title='Deal OF', owner=sale,
                                     est_value_vnd=100_000_000, probability=20)
    return cust, opp


def _client(user):
    c = APIClient(); c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_activity_advances_to_qualify(sale, deal):
    """Ghi nhận cuộc gọi gắn deal → tự sang Thẩm định."""
    cust, opp = deal
    c = _client(sale)
    r = c.post('/api/v1/crm/activities/', {
        'customer': str(cust.id), 'opportunity': str(opp.id),
        'activity_type': 'call', 'content': 'Gọi chào hàng',
        'activity_date': '2026-07-17T09:00:00Z'}, format='json')
    assert r.status_code == 201, r.data
    opp.refresh_from_db(); assert opp.stage == OppStage.QUALIFY


@pytest.mark.django_db
def test_quote_lifecycle_advances_to_won(sale, deal):
    """Tạo báo giá (auto-link deal mở duy nhất) → Đề xuất; CK 0% tự duyệt → Đàm phán;
    to-order → Thắng + probability 100. Không cần kéo thả bước nào."""
    from apps.catalog.models import Part
    from apps.crm.models import Quote
    cust, opp = deal
    Part.objects.create(tokin_part_no='OF-P1', category='Tip',
                        display_name_vi='Bép OF', price_vnd=100000)
    c = _client(sale)
    r = c.post('/api/v1/crm/quotes/', {
        'customer': str(cust.id),
        'lines': [{'part_no': 'OF-P1', 'part_name': 'Bép OF', 'qty': 2,
                   'unit_price_vnd': 100000}]}, format='json')
    assert r.status_code == 201, r.data
    quote = Quote.objects.get(pk=r.data['id'])
    assert quote.opportunity_id == opp.id            # auto-link deal mở duy nhất
    opp.refresh_from_db()
    assert opp.stage == OppStage.NEGOTIATE           # proposal → negotiate (tự duyệt 0%)

    r = c.post(f'/api/v1/crm/quotes/{quote.id}/to-order/')
    assert r.status_code == 200, r.data
    opp.refresh_from_db()
    assert opp.stage == OppStage.WON and opp.probability == 100


@pytest.mark.django_db
def test_no_backward_or_after_closed(sale, deal):
    """Deal đã Thắng → sự kiện mới KHÔNG kéo lùi/không đổi giai đoạn."""
    from apps.crm import opportunity_flow as oflow
    cust, opp = deal
    opp.stage = OppStage.WON; opp.save(update_fields=['stage'])
    assert oflow.advance(opp, OppStage.QUALIFY, sale, 'test') is False
    opp.refresh_from_db(); assert opp.stage == OppStage.WON


@pytest.mark.django_db
def test_mark_lost_requires_reason(sale, deal):
    """Đánh dấu thua: thiếu lý do → 400 kèm danh sách; đủ → lost + lưu lý do."""
    cust, opp = deal
    c = _client(sale)
    base = f'/api/v1/crm/opportunities/{opp.id}/mark-lost/'
    r = c.post(base, {}, format='json')
    assert r.status_code == 400 and 'choices' in r.data
    r = c.post(base, {'reason': 'price', 'note': 'Đối thủ rẻ hơn 12%'}, format='json')
    assert r.status_code == 200, r.data
    opp.refresh_from_db()
    assert opp.stage == OppStage.LOST
    assert opp.lost_reason == 'price' and 'rẻ hơn' in opp.lost_note
    assert opp.probability == 0
    # Đã thua → không đánh dấu lại
    assert c.post(base, {'reason': 'other'}, format='json').status_code == 400


@pytest.mark.django_db
def test_quote_no_autolink_when_two_open_deals(sale, deal):
    """KH có 2 deal mở → KHÔNG đoán bừa (không auto-link, không auto-advance)."""
    from apps.catalog.models import Part
    from apps.crm.models import Quote
    cust, opp = deal
    opp2 = Opportunity.objects.create(customer=cust, title='Deal OF 2', owner=sale)
    Part.objects.create(tokin_part_no='OF-P2', category='Tip',
                        display_name_vi='Bép OF2', price_vnd=50000)
    c = _client(sale)
    r = c.post('/api/v1/crm/quotes/', {
        'customer': str(cust.id),
        'lines': [{'part_no': 'OF-P2', 'part_name': 'Bép OF2', 'qty': 1,
                   'unit_price_vnd': 50000}]}, format='json')
    assert r.status_code == 201
    assert Quote.objects.get(pk=r.data['id']).opportunity_id is None
    opp.refresh_from_db(); opp2.refresh_from_db()
    assert opp.stage == OppStage.PROSPECT and opp2.stage == OppStage.PROSPECT
