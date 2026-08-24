from urllib.parse import urlparse

from django.conf import settings
from django.db import migrations


def sync_site_domain(apps, schema_editor):
    # django.contrib.sites' Site(pk=1, domain='example.com') row isn't created
    # by a migration at all — it's a post_migrate signal (create_default_site,
    # sites/management.py) that runs *after every migration in this run has
    # already applied*, and only if no Site row exists yet. So this can't
    # .filter().update() an existing row (there may not be one yet on a fresh
    # database — the signal fires later); it has to create the row itself,
    # which then makes the signal's own "if not Site.objects.exists()" check
    # a no-op. django_comments/django_comments_xtd build absolute links in
    # confirmation/follow-up emails from Site.domain; every other absolute-link
    # email in this project already uses SITE_BASE_URL (newsletter/tasks.py,
    # newsletter/emails.py) — reused here instead of a second, easy-to-forget
    # env var. Data migration, not a fixture, so it re-syncs on every deploy
    # if SITE_BASE_URL ever changes.
    Site = apps.get_model('sites', 'Site')
    domain = urlparse(settings.SITE_BASE_URL).netloc or settings.SITE_BASE_URL
    Site.objects.update_or_create(
        pk=settings.SITE_ID, defaults={'domain': domain, 'name': settings.JOURNAL_NAME},
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0018_alter_article_short_code_unique'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(sync_site_domain, noop),
    ]
