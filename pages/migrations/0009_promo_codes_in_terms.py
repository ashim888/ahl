# Promo codes and free trials (billing/promotions.py): their rules in the
# Terms of use. Updates the untouched, unpublished draft only.
from django.db import migrations

ANCHOR = '<li>A special article you buy stays readable on your account.</li>'
ADDED = ANCHOR + '''
<li><strong>Promo codes and free trials.</strong> A code's conditions (what it applies to, who can use it, until when,
and how many times) are shown with the offer; one code per order, and a code can't be exchanged for cash or applied to
an order already paid. Student and partner codes need a confirmed email address at the eligible organization. A free
trial is for people who haven't subscribed before, needs no payment details and simply ends — nothing renews. We may
withdraw a code that is being misused.</li>'''


def apply_change(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    page = SitePage.objects.filter(slug='terms').first()
    if page and not page.is_published and page.updated_by_id is None and ANCHOR in page.body_en \
            and 'Promo codes and free trials' not in page.body_en:
        page.body = page.body_en = page.body_en.replace(ANCHOR, ADDED, 1)
        page.save(update_fields=['body', 'body_en'])


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0008_faq_draft'),
    ]

    operations = [
        migrations.RunPython(apply_change, migrations.RunPython.noop),
    ]
