# Fact checks are always free (Article.save): open up any saved behind the paywall.
from django.db import migrations


def free_fact_checks(apps, schema_editor):
    Article = apps.get_model('articles', 'Article')
    Article.objects.filter(article_type='fact_check').exclude(access_type='open_access').update(
        access_type='open_access', price=None)


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0064_survey'),
    ]

    operations = [
        migrations.RunPython(free_fact_checks, migrations.RunPython.noop),
    ]
