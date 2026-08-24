from django.db import migrations, models

# Split into three migrations (this one, 0017 data backfill, 0018 add the
# unique constraint) rather than one AddField(unique=True) — existing rows
# would all default to short_code='', which the unique index rejects
# immediately (confirmed: MySQL 8's atomic DDL rolled the single-migration
# version back cleanly with a duplicate-entry error rather than leaving a
# partial column, which is what made the problem obvious before it ever
# reached a real deployment).


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0015_article_fulltext_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='article',
            name='short_code',
            field=models.CharField(
                blank=True, editable=False, default='', max_length=5,
                help_text='Auto-generated permalink code — also reachable at /articles/<code>/.',
            ),
        ),
        migrations.AlterField(
            model_name='article',
            name='slug',
            field=models.SlugField(
                max_length=500, unique=True, blank=True,
                help_text='Leave blank to generate from the title (plus a short unique code, e.g. "my-article-3f2a4").',
            ),
        ),
    ]
