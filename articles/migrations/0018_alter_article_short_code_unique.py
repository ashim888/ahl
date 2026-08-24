from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0017_backfill_article_short_code'),
    ]

    operations = [
        migrations.AlterField(
            model_name='article',
            name='short_code',
            field=models.CharField(
                blank=True, editable=False, max_length=5, unique=True,
                help_text='Auto-generated permalink code — also reachable at /articles/<code>/.',
            ),
        ),
    ]
