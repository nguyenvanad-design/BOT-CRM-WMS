"""Test cổng lead-intake cho bot khách (ghi-1-chiều, có khóa)."""
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.models import Lead


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_lead_intake_creates_lead():
    User.objects.create(username='s_owner', role=Role.SALES)
    c = APIClient()
    r = c.post('/api/v1/crm/lead-intake/',
               {'name': 'Khách A', 'phone': '0901234567', 'company': 'ABC',
                'note': 'Cần báo giá bép hàn'},
               format='json', HTTP_X_INTAKE_KEY='test-key')
    assert r.status_code == 201 and r.data['ok'] is True
    lead = Lead.objects.get()
    assert lead.name == 'Khách A' and lead.source == 'chatbot_khach'
    assert lead.owner.role == Role.SALES and lead.notes == 'Cần báo giá bép hàn'


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_lead_intake_rejects_bad_key():
    User.objects.create(username='s_owner', role=Role.SALES)
    c = APIClient()
    r = c.post('/api/v1/crm/lead-intake/', {'name': 'X', 'phone': '09'},
               format='json', HTTP_X_INTAKE_KEY='wrong')
    assert r.status_code == 401
    assert Lead.objects.count() == 0


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='test-key')
def test_lead_intake_needs_name_or_phone():
    User.objects.create(username='s_owner', role=Role.SALES)
    c = APIClient()
    r = c.post('/api/v1/crm/lead-intake/', {'company': 'ABC'},
               format='json', HTTP_X_INTAKE_KEY='test-key')
    assert r.status_code == 400


@pytest.mark.django_db
@override_settings(LEAD_INTAKE_KEY='')
def test_lead_intake_disabled_when_no_key():
    c = APIClient()
    r = c.post('/api/v1/crm/lead-intake/', {'name': 'X'},
               format='json', HTTP_X_INTAKE_KEY='anything')
    assert r.status_code == 401
