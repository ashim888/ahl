# Schedules admin_custom.retention.prune_analytics_events to run daily via
# Django-Q's own Schedule model — same pattern as
# sections/migrations/0004_topic_digest_schedule.py: the qcluster worker the
# newsletter already requires picks it up, no cron entry needed.
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = 'analytics_retention_daily'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func='admin_custom.retention.prune_analytics_events',
        schedule_type='D',  # django_q.models.Schedule.DAILY
        repeats=-1,
        next_run=timezone.now(),
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
