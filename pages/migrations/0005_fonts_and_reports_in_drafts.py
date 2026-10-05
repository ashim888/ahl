# Policy drafts, continued: fonts are now self-hosted (Google Fonts no longer
# receives visitors' IP addresses), and readers can report articles and
# comments (/report/). Same rule as before — only pages nobody has edited or
# published are updated.
import importlib
import re

from django.db import migrations

_base = importlib.import_module('pages.migrations.0003_broader_policy_drafts')

CHANGES = [
    ('privacy', 'our hosting provider, Google Analytics (usage statistics), Google Fonts (typefaces), and Cloudflare Turnstile',
     'our hosting provider, Google Analytics (usage statistics, only if you accept analytics cookies), and Cloudflare Turnstile'),
    ('privacy', '<li><strong>When you contact us:</strong> whatever you choose to tell us.</li>',
     '<li><strong>Reports:</strong> if you report an article or comment, what you tell us and, if you give them, your '
     'name and email — so we can act and reply. We never share them with the person you report. We keep reports as the '
     'record of what was reported and what we did.</li>'
     '<li><strong>When you contact us:</strong> whatever you choose to tell us.</li>'),
    ('terms', 'We may edit, hide or remove contributions, and suspend accounts, that break these rules.</p>',
     'We may edit, hide or remove contributions, and suspend accounts, that break these rules. To report a comment or '
     'an article, use the "Report" link next to it.</p>'),
    ('terms', '<li>Articles we mark as free or open access may come with their own licence',
     '<li>If you believe something on {name} uses your copyrighted work, or shares your private information, without '
     'permission, use the "Report" link on the page (or write to us) saying which work is yours and where it appears. '
     'We act on valid notices promptly.</li><li>Articles we mark as free or open access may come with their own licence'),
]


def apply_changes(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    drafts = _base._drafts()
    name = re.search(r'Reading ([^<]+)</h2>', drafts['terms'][1]).group(1)
    for slug in ('privacy', 'terms'):
        page = SitePage.objects.filter(slug=slug).first()
        if page is None or page.is_published or page.updated_by_id is not None:
            continue
        text = page.body_en
        for page_slug, old, new in CHANGES:
            if page_slug == slug and old in text:
                text = text.replace(old, new.replace('{name}', name))
        page.body = page.body_en = _base._tidy(text)
        page.save(update_fields=['body', 'body_en'])


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0004_privacy_rights_in_drafts'),
    ]

    operations = [
        migrations.RunPython(apply_changes, migrations.RunPython.noop),
    ]
