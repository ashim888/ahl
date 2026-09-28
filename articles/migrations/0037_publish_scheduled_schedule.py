# Runs articles.tasks.publish_due_articles every minute on the Django-Q
# worker — the same Schedule pattern as the digests and analytics retention.
from django.db import migrations

SCHEDULE_NAME = 'publish_scheduled_articles'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func='articles.tasks.publish_due_articles',
        schedule_type='I',  # django_q.models.Schedule.MINUTES
        minutes=1,
        repeats=-1,
    )


def delete_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0036_backfill_published_at'),
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
