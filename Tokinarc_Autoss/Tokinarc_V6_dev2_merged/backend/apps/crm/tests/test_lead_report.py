"""Báo cáo lead theo nguồn."""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.models import Lead


def _lead(owner, source, status='new', campaign=''):
    return Lead.objects.create(name='L', phone='09', source=source, status=status,
                               campaign=campaign, owner=owner,
                               created_by=owner, updated_by=owner)


@pytest.mark.django_db
def test_lead_source_report_counts_and_conversion():
    mgr = User.objects.create(username='lr_mgr', role=Role.MANAGER)
    _lead(mgr, 'facebook_ads', 'converted', 'Tet2026')
    _lead(mgr, 'facebook_ads', 'new', 'Tet2026')
    _lead(mgr, 'chatbot_khach', 'converted')
    c = APIClient(); c.force_authenticate(mgr)
    r = c.get('/api/v1/crm/lead-sources/?days=90')
    assert r.status_code == 200
    assert r.data['summary']['total'] == 3 and r.data['summary']['converted'] == 2
    fb = next(s for s in r.data['by_source'] if s['source'] == 'facebook_ads')
    assert fb['total'] == 2 and fb['converted'] == 1 and fb['conversion_pct'] == 50.0
    assert fb['source_label'] == 'Facebook Ads'
    assert any(c2['campaign'] == 'Tet2026' for c2 in r.data['by_campaign'])


@pytest.mark.django_db
def test_lead_source_report_sale_sees_only_own():
    s1 = User.objects.create(username='lr_s1', role=Role.SALES)
    s2 = User.objects.create(username='lr_s2', role=Role.SALES)
    _lead(s2, 'zalo')
    c = APIClient(); c.force_authenticate(s1)
    r = c.get('/api/v1/crm/lead-sources/')
    assert r.status_code == 200 and r.data['summary']['total'] == 0
