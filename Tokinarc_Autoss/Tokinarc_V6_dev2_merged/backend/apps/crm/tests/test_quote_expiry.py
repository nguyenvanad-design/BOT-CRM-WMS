"""Hạn hiệu lực báo giá: auto-expire + chặn chuyển khi hết hạn."""
import datetime as dt

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.models import Customer, Quote, QuoteStatus
from apps.catalog.models import Part


def _sale():
    return User.objects.create(username='qe_sale', role=Role.SALES)


@pytest.mark.django_db
def test_quote_create_sets_default_valid_until():
    sale = _sale()
    cust = Customer.objects.create(code='KH-QE', name='A', owner=sale,
                                   created_by=sale, updated_by=sale)
    Part.objects.create(tokin_part_no='QE-P', category='Tip', display_name_vi='B', price_vnd=1000)
    c = APIClient(); c.force_authenticate(sale)
    r = c.post('/api/v1/crm/quotes/', {'customer': str(cust.id),
               'lines': [{'part_no': 'QE-P', 'qty': 1, 'unit_price_vnd': 1000}]}, format='json')
    assert r.status_code == 201 and r.data['valid_until']


@pytest.mark.django_db
def test_expire_quotes_command():
    from django.core.management import call_command
    sale = _sale()
    cust = Customer.objects.create(code='KH-QE2', name='A', owner=sale,
                                   created_by=sale, updated_by=sale)
    q = Quote.objects.create(code='BG-EXP', customer=cust, owner=sale,
                             status=QuoteStatus.APPROVED,
                             valid_until=dt.date(2020, 1, 1))
    call_command('expire_quotes')
    q.refresh_from_db()
    assert q.status == QuoteStatus.EXPIRED


@pytest.mark.django_db
def test_expired_quote_blocks_to_order():
    sale = _sale()
    cust = Customer.objects.create(code='KH-QE3', name='A', owner=sale,
                                   created_by=sale, updated_by=sale)
    q = Quote.objects.create(code='BG-EXP2', customer=cust, owner=sale,
                             status=QuoteStatus.APPROVED, valid_until=dt.date(2020, 1, 1))
    c = APIClient(); c.force_authenticate(sale)
    r = c.post(f'/api/v1/crm/quotes/{q.id}/to-order/')
    assert r.status_code == 400 and r.data.get('code') == 'QUOTE_EXPIRED'
