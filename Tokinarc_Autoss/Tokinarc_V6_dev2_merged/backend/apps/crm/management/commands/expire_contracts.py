"""
Tokinarc — apps/crm/management/commands/expire_contracts.py

Chuyển hợp đồng đang hiệu lực (active) đã quá end_date → expired.
Chạy định kỳ (cron/scheduler):  python manage.py expire_contracts
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from apps.crm.models import Contract, ContractStatus


class Command(BaseCommand):
    help = "Chuyển HĐ hiệu lực đã quá hạn → expired."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Chỉ liệt kê, không ghi.')

    def handle(self, *args, dry_run=False, **kw):
        today = date.today()
        qs = Contract.objects.filter(status=ContractStatus.ACTIVE,
                                     end_date__isnull=False, end_date__lt=today)
        codes = list(qs.values_list('code', flat=True))
        if dry_run:
            self.stdout.write(f"[dry-run] {len(codes)} HĐ sẽ hết hạn: {', '.join(codes) or '—'}")
            return
        n = qs.update(status=ContractStatus.EXPIRED)
        self.stdout.write(self.style.SUCCESS(f"Đã chuyển {n} hợp đồng → expired."))
