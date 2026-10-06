from urllib.parse import urlparse

from django.apps import AppConfig
from django.db.models.signals import post_migrate


def sync_site_domain(sender, **kwargs):
    """Keeps django.contrib.sites' Site row in step with SITE_BASE_URL after
    *every* migrate, not just once — migration 0019 only ran on the first
    deploy, so a SITE_BASE_URL set or changed later never reached the
    comments package (which reads Site.domain). update_or_create also makes
    sites' own create_default_site ("example.com") a no-op on a fresh DB.
    """
    from django.conf import settings
    from django.contrib.sites.models import Site

    domain = urlparse(settings.SITE_BASE_URL).netloc or settings.SITE_BASE_URL
    Site.objects.update_or_create(
        pk=settings.SITE_ID, defaults={'domain': domain, 'name': settings.JOURNAL_NAME},
    )


class ArticlesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'articles'

    def ready(self):
        from . import checks  # noqa: F401 — registers the SITE_BASE_URL deploy check
        from . import search_signals  # noqa: F401 — keeps Article.search_text current

        post_migrate.connect(sync_site_domain, sender=self, dispatch_uid='articles.sync_site_domain')
