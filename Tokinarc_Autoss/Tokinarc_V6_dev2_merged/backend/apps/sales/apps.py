from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sales'
    verbose_name = 'Bán hàng & hợp đồng'

    def ready(self):
        """Import handlers để trigger @subscribe đăng ký vào listener registry."""
        try:
            from . import handlers  # noqa: F401
        except Exception:
            import logging
            logging.getLogger(__name__).exception("sales.handlers import failed")
