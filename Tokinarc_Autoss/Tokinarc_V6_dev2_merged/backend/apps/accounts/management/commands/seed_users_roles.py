"""
Tokinarc V6.C — apps/accounts/management/commands/seed_users_roles.py

Tạo admin + vài user mẫu mỗi role để dev/test. Idempotent.

    python manage.py seed_users_roles --admin-password=changeme
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.accounts.models import Role, User

SAMPLE = [
    ('sale1', Role.SALES, 'Trần Văn Minh'),
    ('kho1', Role.WAREHOUSE, 'Nguyễn Thị Kho'),
    ('khotruong1', Role.WAREHOUSE_MANAGER, 'Trần Quản Kho'),
    ('kysu1', Role.SERVICE, 'Lê Dịch Vụ'),
    ('quanly1', Role.MANAGER, 'Phạm Quản Lý'),
    ('ceo1', Role.CEO, 'Đỗ Tổng Giám Đốc'),
]


class Command(BaseCommand):
    help = "Seed admin + user mẫu mỗi role."

    def add_arguments(self, parser):
        parser.add_argument('--admin-username', default='admin')
        parser.add_argument('--admin-password', default='admin12345')
        parser.add_argument('--password', default='tokinarc123')

    def handle(self, admin_username, admin_password, password, **kw):
        admin, created = User.objects.get_or_create(
            username=admin_username,
            defaults={'role': Role.ADMIN, 'is_staff': True, 'is_superuser': True,
                      'display_name': 'Administrator'})
        if created:
            admin.set_password(admin_password)
            admin.save()
        for uname, role, name in SAMPLE:
            u, c = User.objects.get_or_create(
                username=uname, defaults={'role': role, 'display_name': name})
            if c:
                u.set_password(password)
                u.save()
        self.stdout.write(self.style.SUCCESS(
            f"✅ admin '{admin_username}' + {len(SAMPLE)} user mẫu."))
