import django.utils.timezone
from django.db import migrations, models
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    Issue = apps.get_model('issues', 'Issue')
    used = set(Issue.objects.exclude(slug='').order_by('id').values_list('slug', flat=True))
    for issue in Issue.objects.order_by('id'):
        if issue.slug:
            continue
        base = slugify(issue.title) or f'collection-{issue.pk}'
        slug = base
        n = 2
        while slug in used:
            slug = f'{base}-{n}'
            n += 1
        used.add(slug)
        issue.slug = slug
        issue.save(update_fields=['slug'])


class Migration(migrations.Migration):
    """NOTE: this migration was first applied against a MySQL DB where
    django_migrations already disagreed with the live schema (the original
    unique_together on (volume, number) was recorded in migration state but
    never actually existed as a DB constraint — see git history for the
    aborted first attempt). At the time, that live DB had already picked up
    the schema changes below via MySQL's per-statement DDL auto-commit
    (from the failed first attempt), so this migration was applied there
    with database_operations=[] — only its migration *name* needed
    recording, not the DDL itself. That's specific to that one already-
    drifted database: Django only replays a migration's operations once per
    database, keyed by migration name, so restoring the real
    database_operations here does not touch that already-applied DB — it
    only fixes any database seeing this migration for the first time (a
    fresh test DB, or a new environment), which previously got the state
    change recorded without the columns actually existing.
    """

    dependencies = [
        ('issues', '0002_alter_issue_cover_image'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='issue',
            unique_together=set(),
        ),
        migrations.RemoveField(model_name='issue', name='volume'),
        migrations.RemoveField(model_name='issue', name='number'),
        migrations.AlterField(
            model_name='issue',
            name='title',
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name='issue',
            name='publication_date',
            field=models.DateField(blank=True, help_text='Optional — shown on the collection page if set.', null=True),
        ),
        migrations.AddField(
            model_name='issue',
            name='slug',
            field=models.SlugField(blank=True, default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='issue',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterModelOptions(
            name='issue',
            options={'ordering': ['-created_at']},
        ),
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='issue',
            name='slug',
            field=models.SlugField(max_length=255, unique=True),
        ),
    ]
