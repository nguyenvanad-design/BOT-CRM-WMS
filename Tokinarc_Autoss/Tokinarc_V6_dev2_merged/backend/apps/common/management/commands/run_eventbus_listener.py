"""
Tokinarc V6.C-fix2 — apps/common/management/commands/run_eventbus_listener.py

Wrapper Django management command cho `tokinarc.eventbus.listener.run_listener()`.
Worker container (`infra/scripts/worker_entrypoint.sh`) gọi command này trong
loop restart-on-crash.

Usage:
    python manage.py run_eventbus_listener
    python manage.py run_eventbus_listener --channels=order_created,payment_received
    python manage.py run_eventbus_listener --poll-timeout=10

Đặt trong `apps.common` (app không depend vào app nghiệp vụ nào) để khởi
listener TRƯỚC khi import các handler từ apps khác — handler tự register
qua `@subscribe` ở import time.

Khi thêm handler ở app mới (vd `apps/sales/handlers.py` có `@subscribe(...)`):
   1. Sửa file `apps/<app>/apps.py` thêm:
          def ready(self):
              from . import handlers  # noqa: F401
   2. Django auto-import handlers khi app load → handler tự register.
   3. Không cần đụng command này.
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from tokinarc.eventbus.channels import ALL_CHANNELS
from tokinarc.eventbus.listener import _HANDLERS, run_listener

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Khởi LISTEN/NOTIFY listener (long-running)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--channels', default='',
            help='Comma-separated channels để LISTEN. Mặc định: tất cả channel có handler.',
        )
        parser.add_argument(
            '--poll-timeout', type=float, default=5.0,
            help='Giây — interval check connection healthy (mặc định 5).',
        )

    def handle(self, *args, **opts):
        # Force import handler module ở các app — handler tự register qua decorator
        # khi module được import lần đầu. Nếu app chưa có handlers.py, import miss
        # không lỗi (đã try/except dưới).
        self._import_handlers()

        channels_str = opts['channels'].strip()
        if channels_str:
            channels = [c.strip() for c in channels_str.split(',') if c.strip()]
            invalid = [c for c in channels if c not in ALL_CHANNELS]
            if invalid:
                self.stderr.write(self.style.ERROR(
                    f"Channels không hợp lệ: {invalid}. "
                    f"Xem tokinarc/eventbus/channels.py."
                ))
                return
        else:
            channels = list(_HANDLERS.keys())

        if not channels:
            self.stderr.write(self.style.WARNING(
                "Không có handler nào đăng ký. Listener sẽ idle. "
                "Thêm handlers.py + apps.ready() cho app cần subscribe."
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Listener khởi với {len(channels)} channel: {channels}"
        ))
        run_listener(channels=channels, poll_timeout=opts['poll_timeout'])

    @staticmethod
    def _import_handlers() -> None:
        """Import `apps.<app>.handlers` để trigger @subscribe decorator."""
        from django.apps import apps
        for app_config in apps.get_app_configs():
            if not app_config.name.startswith('apps.'):
                continue
            try:
                __import__(f'{app_config.name}.handlers')
                logger.info("handlers_imported", extra={"app": app_config.name})
            except ImportError:
                pass   # App không có handlers.py — OK
