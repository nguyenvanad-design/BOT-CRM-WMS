"""
Tokinarc V6.C — apps/storage/tests/test_storage.py
"""
from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.storage import services
from apps.storage.models import FileObject


@pytest.fixture
def user(db):
    return User.objects.create(username='u1', role=Role.SALES)


@pytest.mark.django_db
def test_save_upload_creates_fileobject(user):
    f = SimpleUploadedFile('test.txt', b'hello tokinarc', content_type='text/plain')
    obj = services.save_upload(file=f, kind='misc', user=user)
    assert obj.size_bytes == 14
    assert obj.sha256
    assert obj.backend in ('s3', 'local')


@pytest.mark.django_db
def test_dedup_same_content(user):
    f1 = SimpleUploadedFile('a.txt', b'same', content_type='text/plain')
    f2 = SimpleUploadedFile('b.txt', b'same', content_type='text/plain')
    o1 = services.save_upload(file=f1, kind='misc', user=user)
    o2 = services.save_upload(file=f2, kind='misc', user=user)
    assert o1.id == o2.id                 # dedup theo sha256
    assert FileObject.objects.count() == 1


@pytest.mark.django_db
def test_upload_endpoint_requires_auth(user):
    c = APIClient()
    f = SimpleUploadedFile('x.txt', b'data', content_type='text/plain')
    assert c.post('/api/v1/storage/upload/', {'file': f, 'kind': 'misc'}).status_code == 401
    c.force_authenticate(user)
    f2 = SimpleUploadedFile('x.txt', b'data2', content_type='text/plain')
    r = c.post('/api/v1/storage/upload/', {'file': f2, 'kind': 'misc'})
    assert r.status_code == 201
    assert r.data['filename'] == 'x.txt'
