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

    def test_credit_limit_in_360(self, api, sale_user):
        c = CustomerFactory(owner=sale_user, code='KH-CL1', credit_limit_vnd=5_000_000)
        r = api.get(f'/api/v1/crm/customers/{c.id}/360/')
        assert r.status_code == 200
        assert int(r.data['credit_limit_vnd']) == 5_000_000
        assert r.data['credit_over'] is False   # chưa có nợ

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

    def _csv(self, text: str):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile('kh.csv', text.encode('utf-8'), content_type='text/csv')

    def test_import_dry_run(self, manager):
        """dry_run: kiểm tra không ghi DB, báo số tạo được + lỗi."""
        client = APIClient(); client.force_authenticate(manager)
        csv = ("code,name,segment,contact_name,contact_phone\n"
               "KH-7001,Cong ty A,factory,Anh Tuan,0901\n"
               "KH-7002,Cong ty B,dealer,,\n"
               "X-7003,Sai ma,,,\n"           # lỗi: mã không bắt đầu KH
               ",Thieu ma,,,\n")              # lỗi: thiếu mã
        r = client.post('/api/v1/crm/customers/import/?dry_run=1',
                        {'file': self._csv(csv)}, format='multipart')
        assert r.status_code == 200
        assert r.data['will_create'] == 2
        assert len(r.data['errors']) == 2
        assert not Customer.objects.filter(code='KH-7001').exists()   # chưa ghi

    def test_import_creates_customers_and_contacts(self, manager):
        client = APIClient(); client.force_authenticate(manager)
        csv = ("code,name,segment,contact_name,contact_phone\n"
               "KH-7101,Cong ty A,factory,Anh Tuan,0901\n"
               "KH-7102,Cong ty B,dealer,,\n")
        r = client.post('/api/v1/crm/customers/import/',
                        {'file': self._csv(csv)}, format='multipart')
        assert r.status_code == 200
        assert r.data['created'] == 2
        a = Customer.objects.get(code='KH-7101')
        assert a.segment == 'factory' and a.owner == manager
        assert a.contacts.filter(is_primary=True, full_name='Anh Tuan').exists()

    def test_import_skips_existing(self, manager, sale_user):
        CustomerFactory(owner=sale_user, code='KH-7201', name='Da co')
        client = APIClient(); client.force_authenticate(manager)
        csv = "code,name\nKH-7201,Trung ma\nKH-7202,Moi\n"
        r = client.post('/api/v1/crm/customers/import/',
                        {'file': self._csv(csv)}, format='multipart')
        assert r.data['created'] == 1 and r.data['skipped_existing'] == 1

    def test_import_blocked_for_sale(self, api):
        r = api.post('/api/v1/crm/customers/import/',
                     {'file': self._csv('code,name\nKH-7301,X\n')}, format='multipart')
        assert r.status_code == 403

    def test_import_template_download(self, manager):
        client = APIClient(); client.force_authenticate(manager)
        r = client.get('/api/v1/crm/customers/import-template/')
        assert r.status_code == 200
        assert 'spreadsheet' in r['Content-Type']

    # ── Phase 2: leads / contracts / orders ──
    def test_import_leads(self, manager):
        from apps.crm.models import Lead
        client = APIClient(); client.force_authenticate(manager)
        csv = "name,company,phone,status\nAnh Hung,XYZ,0907,new\n,KhongTen,0908,new\n"
        r = client.post('/api/v1/crm/import/leads/', {'file': self._csv(csv)}, format='multipart')
        assert r.status_code == 200
        assert r.data['created'] == 1 and len(r.data['errors']) == 1
        assert Lead.objects.filter(name='Anh Hung', owner=manager).exists()

    def test_import_contracts_resolves_customer(self, manager, sale_user):
        from apps.crm.models import Contract
        CustomerFactory(owner=sale_user, code='KH-8001', name='ACME')
        client = APIClient(); client.force_authenticate(manager)
        csv = ("code,customer_code,title,value_vnd,status\n"
               "HD-9001,KH-8001,HD khung,500.000.000,active\n"
               "HD-9002,KH-XXXX,Sai KH,1000,active\n")    # KH không tồn tại → lỗi
        r = client.post('/api/v1/crm/import/contracts/', {'file': self._csv(csv)}, format='multipart')
        assert r.data['created'] == 1 and len(r.data['errors']) == 1
        ct = Contract.objects.get(code='HD-9001')
        assert int(ct.value_vnd) == 500_000_000 and ct.customer.code == 'KH-8001'

    def test_import_orders(self, manager, sale_user):
        from apps.sales.models import SalesOrder
        CustomerFactory(owner=sale_user, code='KH-8101', name='ACME2')
        client = APIClient(); client.force_authenticate(manager)
        csv = ("code,customer_code,issued_date,total_vnd,paid_vnd,status\n"
               "DH-9001,KH-8101,2024-03-20,120000000,120000000,completed\n"
               "DH-9002,KH-8101,2024-03-21,1000,5000,completed\n")   # paid>total → lỗi
        r = client.post('/api/v1/crm/import/orders/', {'file': self._csv(csv)}, format='multipart')
        assert r.data['created'] == 1 and len(r.data['errors']) == 1
        assert SalesOrder.objects.filter(code='DH-9001').exists()

    def test_import_entity_blocked_for_sale(self, api):
        r = api.post('/api/v1/crm/import/leads/',
                     {'file': self._csv('name\nAnh A\n')}, format='multipart')
        assert r.status_code == 403

    def test_import_entity_unknown_404(self, manager):
        client = APIClient(); client.force_authenticate(manager)
        r = client.get('/api/v1/crm/import/khong_co/template/')
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
