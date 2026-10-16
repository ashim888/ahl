# Deletes expired sessions daily (Django's `clearsessions`). Sessions live in
# the database and every cookieless article view (crawlers, first visits)
# saves one (articles/views.py _record_article_view), so without this the
# table only grows. Same Schedule pattern as 0001_analytics_retention_schedule.
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = 'clear_sessions_daily'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func='django.core.management.call_command',
        args="'clearsessions'",
        schedule_type='D',  # django_q.models.Schedule.DAILY
        repeats=-1,
        next_run=timezone.now(),
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('admin_custom', '0004_worker_heartbeat_schedule'),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
