from django.apps import AppConfig


class PitchesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pitches'

    def ready(self):
        from . import signals  # noqa: F401
