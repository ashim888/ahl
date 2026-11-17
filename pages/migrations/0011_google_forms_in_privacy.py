# Surveys embedded in stories are Google Forms (articles/survey.py): say who
# receives the answers, and that Google may set its own cookies in the form.
# Updates the untouched, unpublished privacy draft only.
from django.db import migrations

CHANGES = [
    ("privacy policy applies once you press play.</li>\n",
     "privacy policy applies once you press play.</li>\n"
     "<li><strong>Google Forms</strong>, when you answer a survey in one of our stories. Your answers go to our editors "
     "through Google, and Google's own privacy policy applies to them.</li>\n"),
    ('We ask again after 6 months.</p>',
     'We ask again after 6 months.</p>\n'
     '<p><strong>Surveys:</strong> some stories include a survey run on Google Forms. Nothing loads from Google until '
     'you choose to open the survey; once you do, Google may set its own cookies inside it, under Google\'s privacy '
     'policy. Our cookie settings don\'t cover these; you can block them in your browser.</p>'),
]


def apply_change(apps, schema_editor):
    SitePage = apps.get_model('pages', 'SitePage')
    page = SitePage.objects.filter(slug='privacy').first()
    if not page or page.is_published or page.updated_by_id is not None:
        return
    body = page.body_en
    for old, new in CHANGES:
        body = body.replace(old, new, 1)
    if body != page.body_en:
        page.body = page.body_en = body
        page.save(update_fields=['body', 'body_en'])


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0010_clear_blank_nepali_text'),
    ]

    operations = [
        migrations.RunPython(apply_change, migrations.RunPython.noop),
    ]
