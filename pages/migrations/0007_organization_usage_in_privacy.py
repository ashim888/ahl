# Institutional usage reports (billing/org_reports.py): organizations see how
# many articles each member read through their subscription, never which.
# Updates the untouched, unpublished privacy draft only.
from django.db import migrations

CHANGES = [
    ("<li><strong>Organization access:</strong> that you joined your organization's subscription, and when.</li>",
     "<li><strong>Organization access:</strong> that you joined your organization's subscription, and when, and the "
     "articles you read through it (one entry per article per day) — for its usage report.</li>"),
    ("<li><strong>Your organization</strong>, if you read through its subscription — it may be told that you joined.</li>",
     "<li><strong>Your organization</strong>, if you read through its subscription: its managers see your name, email, "
     "when you joined, <strong>how many</strong> articles you read and when you last read — <strong>never which "
     "articles</strong>. Its most-read articles are reported only for the organization as a whole. If you erase your "
     "account, your past reads stay in its totals without your name.</li>"),
]


def apply_change(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    page = SitePage.objects.filter(slug='privacy').first()
    if not page or page.is_published or page.updated_by_id is not None:
        return
    body = page.body_en
    for old, new in CHANGES:
        body = body.replace(old, new)
    if body != page.body_en:
        page.body = page.body_en = body
        page.save(update_fields=['body', 'body_en'])


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0006_three_day_cancellation'),
    ]

    operations = [
        migrations.RunPython(apply_change, migrations.RunPython.noop),
    ]
