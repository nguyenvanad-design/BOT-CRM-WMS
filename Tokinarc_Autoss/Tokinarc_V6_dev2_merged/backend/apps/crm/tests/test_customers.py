"""
Tokinarc V6.C — apps/crm/tests/test_customers.py

Pattern test dùng cho mọi app:
  - factory-boy cho fixture (gọn, composable hơn pytest fixture thuần)
  - pytest-django với @pytest.mark.django_db
  - DRF APIClient — gọi endpoint thật, không gọi viewset trực tiếp
  - Test cả 3 góc: serializer, permission, business logic
"""
from __future__ import annotations

import factory
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.crm.models import Contact, Customer

User = get_user_model()


# ─── Factories ───────────────────────────────────────────────────────────────
class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
    username = factory.Sequence(lambda n: f'user{n}')
    email    = factory.LazyAttribute(lambda o: f'{o.username}@tokinarc.test')
    role     = 'sales'


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer
    code    = factory.Sequence(lambda n: f'KH-{n:04d}')
    name    = factory.Faker('company', locale='vi_VN')
    segment = 'factory'
    status  = 'new'
    owner   = factory.SubFactory(UserFactory)


class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contact
    customer  = factory.SubFactory(CustomerFactory)
    full_name = factory.Faker('name', locale='vi_VN')
    phone     = factory.Faker('phone_number', locale='vi_VN')


# ─── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def sale_user(db):
    return UserFactory(role='sales')


@pytest.fixture
def other_sale(db):
    return UserFactory(role='sales')


@pytest.fixture
def manager(db):
    return UserFactory(role='manager')


@pytest.fixture
def customer_user(db):
    return UserFactory(role='customer')


@pytest.fixture
def api(sale_user):
    """APIClient logged in as sale_user."""
    c = APIClient()
    c.force_authenticate(sale_user)
    return c


# ─── Model & serializer tests ────────────────────────────────────────────────
@pytest.mark.django_db
class TestCustomerModel:

    def test_create_and_str(self, sale_user):
        c = CustomerFactory(owner=sale_user, code='KH-0001', name='Công ty A')
        assert str(c) == 'KH-0001 — Công ty A'

    def test_soft_delete(self, sale_user):
        c = CustomerFactory(owner=sale_user)
        c.soft_delete(user=sale_user)
        # Default manager hides
        assert not Customer.objects.filter(pk=c.pk).exists()
        # all_objects sees
        assert Customer.all_objects.filter(pk=c.pk).exists()
        # restore
        c.refresh_from_db()
        c.restore()
        assert Customer.objects.filter(pk=c.pk).exists()

    def test_only_one_primary_contact_per_customer(self, sale_user):
        from django.db import IntegrityError
        c = CustomerFactory(owner=sale_user)
        ContactFactory(customer=c, full_name='A', is_primary=True)
        with pytest.raises(IntegrityError):
            ContactFactory(customer=c, full_name='B', is_primary=True)


# ─── API tests — permission + behavior ──────────────────────────────────────
@pytest.mark.django_db
class TestCustomerAPI:

    def test_list_only_returns_own_customers_for_sale(self, api, sale_user, other_sale):
        CustomerFactory(owner=sale_user, code='KH-0001')
        CustomerFactory(owner=other_sale, code='KH-0002')
        r = api.get('/api/v1/crm/customers/')
        assert r.status_code == 200
        codes = {x['code'] for x in r.data['results']}
        assert codes == {'KH-0001'}

    def test_manager_sees_all(self, manager, sale_user):
        client = APIClient(); client.force_authenticate(manager)
        CustomerFactory(owner=sale_user, code='KH-0001')
        CustomerFactory(owner=manager,   code='KH-0002')
        r = client.get('/api/v1/crm/customers/')
        assert r.status_code == 200
        assert r.data['count'] == 2

    def test_create_assigns_owner_to_self_for_sale(self, api, sale_user, other_sale):
        # Sale gửi owner=other_sale, BE phải override về self
        r = api.post('/api/v1/crm/customers/', {
            'code': 'KH-0009', 'name': 'XYZ',
            'segment': 'factory', 'owner': other_sale.id,
        }, format='json')
        assert r.status_code == 201
        assert r.data['owner'] == sale_user.id

    def test_manager_can_override_owner(self, manager, sale_user):
        client = APIClient(); client.force_authenticate(manager)
        r = client.post('/api/v1/crm/customers/', {
            'code': 'KH-0010', 'name': 'ABC',
            'segment': 'dealer', 'owner': sale_user.id,
        }, format='json')
        assert r.status_code == 201
        assert r.data['owner'] == sale_user.id

    def test_other_sale_cannot_update(self, sale_user, other_sale):
        c = CustomerFactory(owner=sale_user, code='KH-0011')
        client = APIClient(); client.force_authenticate(other_sale)
        r = client.patch(f'/api/v1/crm/customers/{c.id}/', {'name': 'Hack'}, format='json')
        assert r.status_code == 404  # filtered out, looks like not found

    def test_customer_role_cannot_write(self, customer_user):
        client = APIClient(); client.force_authenticate(customer_user)
        r = client.post('/api/v1/crm/customers/', {
            'code': 'KH-0099', 'name': 'BadActor', 'segment': 'other',
        }, format='json')
        assert r.status_code == 403

    def test_delete_is_soft(self, api, sale_user):
        c = CustomerFactory(owner=sale_user, code='KH-0020')
        r = api.delete(f'/api/v1/crm/customers/{c.id}/')
        assert r.status_code == 204
        assert not Customer.objects.filter(pk=c.id).exists()
        assert Customer.all_objects.filter(pk=c.id).exists()

    def test_code_must_start_with_KH(self, api):
        r = api.post('/api/v1/crm/customers/', {
            'code': 'X-0001', 'name': 'Bad code', 'segment': 'other',
        }, format='json')
        assert r.status_code == 400
        assert 'code' in r.data

    def test_360_endpoint(self, api, sale_user):
        c = CustomerFactory(owner=sale_user, code='KH-0021')
        r = api.get(f'/api/v1/crm/customers/{c.id}/360/')
        assert r.status_code == 200
        assert r.data['open_orders'] == 0
        assert r.data['debt_vnd'] in ('0', 0)

    def test_timeline_endpoint(self, api, sale_user):
        """Lịch sử làm việc gộp Visit + Activity, sắp giảm dần theo thời gian."""
        import datetime as dt

        from apps.crm.models import Activity, Visit
        c = CustomerFactory(owner=sale_user, code='KH-0050')
        Visit.objects.create(customer=c, owner=sale_user, visit_date=dt.date(2026, 6, 10),
                             purpose='Demo súng hàn', summary='Khách quan tâm',
                             next_action='Gửi báo giá')
        Activity.objects.create(customer=c, owner=sale_user, activity_type='call',
                                content='Gọi chốt lịch', activity_date=dt.datetime(2026, 6, 15, 9, 0))
        r = api.get(f'/api/v1/crm/customers/{c.id}/timeline/')
        assert r.status_code == 200
        assert r.data['count'] == 2
        kinds = [e['kind'] for e in r.data['results']]
        assert kinds == ['activity', 'visit']   # 15/06 trước 10/06
        assert r.data['results'][0]['title'] == 'Gọi điện'

    def test_timeline_respects_ownership(self, sale_user, other_sale):
        """Sale khác không xem được timeline KH không thuộc mình (404)."""
        c = CustomerFactory(owner=sale_user, code='KH-0051')
        client = APIClient(); client.force_authenticate(other_sale)
        r = client.get(f'/api/v1/crm/customers/{c.id}/timeline/')
        assert r.status_code == 404

    def test_visit_recording_and_recap(self, api, sale_user):
        """Tạo Visit kèm file ghi âm + văn bản recap → lưu & hiện trên timeline."""
        import datetime as dt

        from apps.crm.models import Visit
        from apps.storage.models import FileObject
        c = CustomerFactory(owner=sale_user, code='KH-0052')
        audio = FileObject.objects.create(
            kind='visit_recording', filename='ghiam.m4a', mime_type='audio/mp4',
            size_bytes=1024, path='visit_recording/aa/x.m4a', sha256='a' * 64)

        # Tạo visit qua API kèm recording + recap_text
        r = api.post('/api/v1/crm/visits/', {
            'customer': str(c.id), 'visit_date': '2026-06-20', 'purpose': 'Demo',
            'recording': str(audio.id), 'recap_text': 'Khách chốt mua 10 bộ',
        }, format='json')
        assert r.status_code == 201
        assert r.data['recap_text'] == 'Khách chốt mua 10 bộ'
        assert r.data['recording_info']['filename'] == 'ghiam.m4a'

        v = Visit.objects.get(customer=c)
        assert v.recording_id == audio.id

        # Timeline hiện recap (ưu tiên recap_text) + link ghi âm
        t = api.get(f'/api/v1/crm/customers/{c.id}/timeline/')
        ev = t.data['results'][0]
        assert ev['detail'] == 'Khách chốt mua 10 bộ'
        assert ev['recording_url'] and str(audio.id) in ev['recording_url']

    def test_audit_log_on_create(self, api, sale_user):
        from apps.common.models import AuditLog
        r = api.post('/api/v1/crm/customers/', {
            'code': 'KH-0030', 'name': 'AuditMe', 'segment': 'other',
        }, format='json')
        assert r.status_code == 201
        log = AuditLog.objects.filter(entity='crm.Customer', action='create').last()
        assert log is not None
        assert log.user_id == sale_user.id

    def test_nested_contacts_create(self, api):
        r = api.post('/api/v1/crm/customers/', {
            'code': 'KH-0040', 'name': 'Nested', 'segment': 'oem',
            'contacts': [
                {'full_name': 'Anh Tuấn', 'phone': '0901', 'is_primary': True},
                {'full_name': 'Chị Hoa', 'phone': '0902'},
            ],
        }, format='json')
        assert r.status_code == 201
        assert len(r.data['contacts']) == 2

    def test_nested_contacts_validate_one_primary(self, api):
        r = api.post('/api/v1/crm/customers/', {
            'code': 'KH-0041', 'name': 'BadNested', 'segment': 'oem',
            'contacts': [
                {'full_name': 'A', 'is_primary': True},
                {'full_name': 'B', 'is_primary': True},
            ],
        }, format='json')
        assert r.status_code == 400
        assert 'contacts' in r.data
