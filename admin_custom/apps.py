from django.apps import AppConfig


class AdminCustomConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'admin_custom'

    def ready(self):
        from . import signals  # noqa: F401 — new-comment staff alerts
