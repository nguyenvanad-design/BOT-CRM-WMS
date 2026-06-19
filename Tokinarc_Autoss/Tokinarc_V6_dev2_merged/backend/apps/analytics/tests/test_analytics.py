"""
Tokinarc V6.C — apps/analytics/tests/test_analytics.py
"""
from __future__ import annotations

import datetime as dt

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.crm.models import Customer
from apps.sales.models import SalesOrder


@pytest.fixture
def manager(db):
    return User.objects.create(username='mgr', role=Role.MANAGER)


@pytest.fixture
def sale(db):
    return User.objects.create(username='s1', role=Role.SALES)


@pytest.fixture
def seeded(db, sale):
    cust = Customer.objects.create(code='KH-9001', name='ACME', segment='factory', owner=sale)
    SalesOrder.objects.create(code='HD-9001', customer=cust, issued_date=dt.date(2026, 6, 1),
                              total_vnd=1000000, paid_vnd=600000, status='active', owner=sale)
    SalesOrder.objects.create(code='HD-9002', customer=cust, issued_date=dt.date(2026, 6, 10),
                              total_vnd=2000000, paid_vnd=2000000, status='completed', owner=sale)
    return cust


@pytest.mark.django_db
def test_kpi_overview(manager, seeded):
    c = APIClient(); c.force_authenticate(manager)
    r = c.get('/api/v1/analytics/kpi/overview/')
    assert r.status_code == 200
    assert r.data['revenue_vnd'] == 3000000
    assert r.data['debt_vnd'] == 400000


@pytest.mark.django_db
def test_revenue_by_segment(manager, seeded):
    c = APIClient(); c.force_authenticate(manager)
    r = c.get('/api/v1/analytics/revenue/by-segment/')
    assert r.status_code == 200
    assert r.data[0]['segment'] == 'factory'
    assert r.data[0]['revenue_vnd'] == 3000000


@pytest.mark.django_db
def test_sales_role_blocked(sale, seeded):
    c = APIClient(); c.force_authenticate(sale)
    assert c.get('/api/v1/analytics/kpi/overview/').status_code == 403


@pytest.mark.django_db
def test_debt_aging(manager, seeded):
    c = APIClient(); c.force_authenticate(manager)
    r = c.get('/api/v1/analytics/debt-aging/')
    assert r.status_code == 200
    # chỉ HD-9001 còn nợ
    assert r.data['count'] == 1
