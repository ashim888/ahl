# Subscriptions: cancel within 3 days of paying for a full refund, from the
# Billing page (billing.payments.cancel_subscription). Updates untouched,
# unpublished drafts only.
from django.db import migrations

OLD = ("<li>You can get a <strong>full refund if you ask within 7 days of paying</strong>. After that, a subscription "
       "runs until the end of the period you paid for and isn't refunded part-way.</li>")
NEW = ("<li>You can <strong>cancel within 3 days of paying for a full refund</strong> — use <em>Cancel &amp; refund</em> "
       "on your Billing page (or email us). Your access ends when you cancel, and the refund follows as described in "
       "section 8. After 3 days, a subscription runs until the end of the period you paid for and isn't refunded "
       "part-way.</li>")


def apply_change(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    page = SitePage.objects.filter(slug='refund-policy').first()
    if page and not page.is_published and page.updated_by_id is None and OLD in page.body_en:
        page.body = page.body_en = page.body_en.replace(OLD, NEW)
        page.save(update_fields=['body', 'body_en'])


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0005_fonts_and_reports_in_drafts'),
    ]

    operations = [
        migrations.RunPython(apply_change, migrations.RunPython.noop),
    ]
