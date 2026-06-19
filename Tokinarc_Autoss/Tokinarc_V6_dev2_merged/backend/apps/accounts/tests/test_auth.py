"""
Tokinarc V6.C — apps/accounts/tests/test_auth.py
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.accounts import services


@pytest.fixture(autouse=True)
def _clear_lockout():
    # reset in-memory lockout giữa các test
    if services._BACKEND == 'memory':
        services._mem.clear()
    yield


@pytest.fixture
def sale(db):
    u = User.objects.create(username='sale1', role=Role.SALES, display_name='Minh')
    u.set_password('secret12345')
    u.save()
    return u


@pytest.mark.django_db
def test_login_success(sale):
    c = APIClient()
    r = c.post('/api/v1/auth/login/', {'username': 'sale1', 'password': 'secret12345'},
               format='json')
    assert r.status_code == 200
    assert 'access' in r.data and 'refresh' in r.data
    assert r.data['user']['role'] == 'sales'


@pytest.mark.django_db
def test_login_wrong_password(sale):
    c = APIClient()
    r = c.post('/api/v1/auth/login/', {'username': 'sale1', 'password': 'wrong'},
               format='json')
    assert r.status_code == 401
    assert r.data['code'] == 'AUTH_INVALID'


@pytest.mark.django_db
def test_account_lockout_after_5_fails(sale):
    c = APIClient()
    for _ in range(5):
        c.post('/api/v1/auth/login/', {'username': 'sale1', 'password': 'wrong'},
               format='json')
    # lần thứ 6 dù đúng pass cũng bị khóa
    r = c.post('/api/v1/auth/login/', {'username': 'sale1', 'password': 'secret12345'},
               format='json')
    assert r.status_code == 429
    assert r.data['code'] == 'RATE_LIMITED'


@pytest.mark.django_db
def test_me_requires_auth(sale):
    c = APIClient()
    assert c.get('/api/v1/auth/me/').status_code == 401
    c.force_authenticate(sale)
    r = c.get('/api/v1/auth/me/')
    assert r.status_code == 200 and r.data['username'] == 'sale1'


@pytest.mark.django_db
def test_set_role_admin_only(sale):
    admin = User.objects.create(username='ad', role=Role.ADMIN, is_staff=True, is_superuser=True)
    target = User.objects.create(username='t', role=Role.SALES)
    c = APIClient()
    # sale không được
    c.force_authenticate(sale)
    assert c.post(f'/api/v1/accounts/users/{target.id}/set-role/',
                  {'role': 'manager'}, format='json').status_code == 403
    # admin được
    c.force_authenticate(admin)
    r = c.post(f'/api/v1/accounts/users/{target.id}/set-role/',
               {'role': 'manager'}, format='json')
    assert r.status_code == 200 and r.data['role'] == 'manager'


@pytest.mark.django_db
def test_jwks_endpoint():
    c = APIClient()
    r = c.get('/.well-known/jwks.json')
    assert r.status_code == 200 and 'keys' in r.data
