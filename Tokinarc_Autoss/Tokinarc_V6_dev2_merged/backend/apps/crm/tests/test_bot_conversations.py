"""Test lưu & quản lý hội thoại bot khách: ingest (keyed) + staff view/actions + quyền."""
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.bot_conversations import BotConversation, ConvStatus


def _ingest(c, session_key='s1', user_text='xin chào', bot_text='dạ em nghe', **extra):
    payload = {'session_key': session_key, 'user_text': user_text, 'bot_text': bot_text, **extra}
    return c.post('/api/v1/crm/bot-conversations/ingest/', payload,
                  format='json', HTTP_X_INTAKE_KEY='test-key')


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_ingest_creates_conversation_and_appends():
    c = APIClient()
    assert _ingest(c, user_text='còn béc 0.8?', bot_text='dạ còn').status_code == 201
    r = _ingest(c, user_text='đặt 5 cái', bot_text='cho xin sđt ạ',
                customer_phone='0912345678', customer_name='Khách A')
    assert r.status_code == 201
    conv = BotConversation.objects.get(session_key='s1')
    assert conv.message_count == 4                       # 2 lượt × (user+bot)
    assert conv.customer_phone == '0912345678' and conv.customer_name == 'Khách A'
    assert conv.messages.count() == 4
    assert conv.messages.first().role == 'user'


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_ingest_links_lead_by_phone():
    from apps.crm.models import Lead
    User.objects.create(username='s', role=Role.SALES)
    lead = Lead.objects.create(name='Khách A', phone='0912345678', owner=User.objects.first())
    c = APIClient()
    _ingest(c, customer_phone='0912345678')
    conv = BotConversation.objects.get(session_key='s1')
    assert conv.lead_id == lead.id


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_ingest_rejects_bad_key():
    c = APIClient()
    r = c.post('/api/v1/crm/bot-conversations/ingest/', {'session_key': 's1', 'user_text': 'a'},
               format='json', HTTP_X_INTAKE_KEY='wrong')
    assert r.status_code == 401 and BotConversation.objects.count() == 0


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_ingest_needs_content():
    c = APIClient()
    r = c.post('/api/v1/crm/bot-conversations/ingest/', {'session_key': 's1'},
               format='json', HTTP_X_INTAKE_KEY='test-key')
    assert r.status_code == 400


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_staff_list_and_detail():
    c = APIClient()
    _ingest(c, user_text='hỏi giá', bot_text='120k ạ')
    sale = User.objects.create(username='sale1', role=Role.SALES)
    c.force_authenticate(sale)
    lst = c.get('/api/v1/crm/bot-conversations/').json()
    assert lst['count'] == 1 and lst['results'][0]['last_preview']
    cid = lst['results'][0]['id']
    det = c.get(f'/api/v1/crm/bot-conversations/{cid}/').json()
    assert [m['role'] for m in det['messages']] == ['user', 'bot']


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_customer_blocked():
    c = APIClient()
    _ingest(c)
    cust = User.objects.create(username='kh', role=Role.CUSTOMER)
    c.force_authenticate(cust)
    assert c.get('/api/v1/crm/bot-conversations/').status_code == 403


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_actions_assign_flag_note_close():
    c = APIClient()
    _ingest(c)
    conv = BotConversation.objects.get()
    sale = User.objects.create(username='sale1', role=Role.SALES)
    c.force_authenticate(sale)
    base = f'/api/v1/crm/bot-conversations/{conv.id}/'
    assert c.post(base + 'assign/').status_code == 200
    assert c.post(base + 'flag/').json()['flagged'] is True
    assert c.post(base + 'note/', {'text': 'đã gọi'}, format='json').status_code == 200
    assert c.post(base + 'close/').json()['status'] == ConvStatus.CLOSED
    conv.refresh_from_db()
    assert conv.owner_id == sale.id and conv.flagged and conv.status == ConvStatus.CLOSED
    assert conv.messages.filter(role='agent').exists()


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_sale_scope_hides_others_conversations():
    """Sale chỉ thấy hội thoại chưa có chủ + của mình; không thấy của sale khác."""
    c = APIClient()
    _ingest(c, session_key='mine')
    _ingest(c, session_key='other')
    s1 = User.objects.create(username='s1', role=Role.SALES)
    s2 = User.objects.create(username='s2', role=Role.SALES)
    other = BotConversation.objects.get(session_key='other')
    other.owner = s2; other.save(update_fields=['owner'])
    c.force_authenticate(s1)
    keys = {r['session_key'] for r in c.get('/api/v1/crm/bot-conversations/').json()['results']}
    assert 'mine' in keys and 'other' not in keys      # 'other' thuộc s2 → ẩn
    # Manager thấy tất cả
    mgr = User.objects.create(username='m', role=Role.MANAGER)
    c.force_authenticate(mgr)
    assert c.get('/api/v1/crm/bot-conversations/').json()['count'] == 2
