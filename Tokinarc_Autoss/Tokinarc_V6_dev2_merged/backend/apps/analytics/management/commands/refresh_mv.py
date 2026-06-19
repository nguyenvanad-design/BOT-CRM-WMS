"""
Tokinarc V6.C — apps/analytics/management/commands/refresh_mv.py

Cron (B.1 §6) gọi: python manage.py refresh_mv --group=hourly|daily
Production tạo materialized view qua raw SQL migration; lệnh này REFRESH.
Hiện liệt kê tên MV — bật khi MV đã được tạo.
"""
from django.core.management.base import BaseCommand
from django.db import connection

HOURLY = ['mv_monthly_revenue', 'mv_debt_aging', 'mv_top_customers',
          'mv_inventory_value', 'mv_pipeline_forecast']
DAILY = ['mv_installed_base']


class Command(BaseCommand):
    help = "Refresh materialized views."

    def add_arguments(self, parser):
        parser.add_argument('--group', choices=['hourly', 'daily'], default='hourly')

    def handle(self, group, **kw):
        views = HOURLY if group == 'hourly' else DAILY
        with connection.cursor() as cur:
            for v in views:
                try:
                    cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {v};")
                    self.stdout.write(self.style.SUCCESS(f"  refreshed {v}"))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  skip {v}: {e}"))
