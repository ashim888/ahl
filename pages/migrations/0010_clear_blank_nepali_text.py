"""Nepali page text that only looks empty ('<p>&nbsp;</p>', left by the
editor when the box was cleared) becomes truly empty, so readers get the
English page instead of a blank one — see SitePage.save()."""
import re
from html import unescape

from django.db import migrations

VISIBLE_TAG_RE = re.compile(r'<(img|iframe|video|audio|object|embed|svg|hr)\b', re.IGNORECASE)
TAG_RE = re.compile(r'<[^>]+>')


def is_blank_html(html):
    if not html:
        return True
    if VISIBLE_TAG_RE.search(html):
        return False
    return not unescape(TAG_RE.sub('', html)).replace('\xa0', ' ').strip()


def clear_blank(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    for page in SitePage.objects.all():
        changed = [field for field in ('body_ne', 'title_ne') if getattr(page, field) and is_blank_html(getattr(page, field))]
        for field in changed:
            setattr(page, field, '')
        if changed:
            page.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [('pages', '0009_promo_codes_in_terms')]

    operations = [migrations.RunPython(clear_blank, migrations.RunPython.noop)]
