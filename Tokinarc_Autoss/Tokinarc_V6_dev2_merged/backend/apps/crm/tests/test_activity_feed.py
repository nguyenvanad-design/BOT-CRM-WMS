"""Nhật ký hoạt động của sale (my-activity)."""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.models import Activity, Customer, Lead


def _cust(owner):
    return Customer.objects.create(code='KH-AF1', name='ACME', owner=owner,
                                   created_by=owner, updated_by=owner)


@pytest.mark.django_db
def test_my_activity_returns_own_events():
    sale = User.objects.create(username='af_sale', role=Role.SALES)
    c = _cust(sale)
    Activity.objects.create(customer=c, activity_type='call', content='Gọi KH',
                            owner=sale, created_by=sale, updated_by=sale)
    Lead.objects.create(name='Lead A', phone='0900', source='manual', owner=sale,
                        created_by=sale, updated_by=sale)
    cl = APIClient(); cl.force_authenticate(sale)
    r = cl.get('/api/v1/crm/my-activity/?days=7')
    assert r.status_code == 200
    kinds = {e['kind'] for e in r.data['results']}
    assert 'activity' in kinds and 'lead' in kinds


@pytest.mark.django_db
def test_my_activity_sale_sees_only_own():
    s1 = User.objects.create(username='af_s1', role=Role.SALES)
    s2 = User.objects.create(username='af_s2', role=Role.SALES)
    c2 = Customer.objects.create(code='KH-AF2', name='B', owner=s2,
                                 created_by=s2, updated_by=s2)
    Activity.objects.create(customer=c2, activity_type='call', content='x',
                            owner=s2, created_by=s2, updated_by=s2)
    cl = APIClient(); cl.force_authenticate(s1)
    r = cl.get('/api/v1/crm/my-activity/')
    assert r.status_code == 200 and r.data['count'] == 0


@pytest.mark.django_db
def test_my_activity_manager_can_filter_owner():
    mgr = User.objects.create(username='af_mgr', role=Role.MANAGER)
    s2 = User.objects.create(username='af_s3', role=Role.SALES)
    c2 = Customer.objects.create(code='KH-AF3', name='C', owner=s2,
                                 created_by=s2, updated_by=s2)
    Lead.objects.create(name='L', phone='09', source='m', owner=s2,
                        created_by=s2, updated_by=s2)
    cl = APIClient(); cl.force_authenticate(mgr)
    # Không lọc → thấy của team
    assert cl.get('/api/v1/crm/my-activity/').data['count'] >= 1
    # Lọc theo s2
    r = cl.get(f'/api/v1/crm/my-activity/?owner={s2.id}')
    assert r.status_code == 200 and r.data['count'] >= 1
