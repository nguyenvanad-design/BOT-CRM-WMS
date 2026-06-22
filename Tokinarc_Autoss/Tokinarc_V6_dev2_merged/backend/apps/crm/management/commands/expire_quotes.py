"""
Tokinarc — apps/crm/management/commands/expire_quotes.py

Chuyển báo giá còn hiệu lực (chưa chốt) đã quá valid_until → expired.
Chạy định kỳ (cron/scheduler):  python manage.py expire_quotes
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from apps.crm.models import Quote, QuoteStatus

# Trạng thái còn "mở" — quá hạn thì hết hiệu lực. KHÔNG đụng converted/rejected.
_OPEN = [QuoteStatus.DRAFT, QuoteStatus.SENT, QuoteStatus.PENDING_CEO, QuoteStatus.APPROVED]


class Command(BaseCommand):
    help = "Chuyển báo giá còn mở đã quá hạn hiệu lực → expired."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Chỉ liệt kê, không ghi.')

    def handle(self, *args, dry_run=False, **kw):
        today = date.today()
        qs = Quote.objects.filter(status__in=_OPEN,
                                  valid_until__isnull=False, valid_until__lt=today)
        codes = list(qs.values_list('code', flat=True))
        if dry_run:
            self.stdout.write(f"[dry-run] {len(codes)} báo giá sẽ hết hạn: {', '.join(codes) or '—'}")
            return
        n = qs.update(status=QuoteStatus.EXPIRED)
        self.stdout.write(self.style.SUCCESS(f"Đã chuyển {n} báo giá → expired."))
