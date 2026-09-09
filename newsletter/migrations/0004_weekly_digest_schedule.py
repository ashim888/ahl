# Schedules newsletter.tasks.send_weekly_digest_issue to run weekly via
# django_q's own Schedule model — same worker process (`qcluster`) the
# topic digest and manual newsletter sends already require, no new
# deployment step. Second use of django_q.Schedule in this project — see
# sections/migrations/0004_topic_digest_schedule.py for the first, and
# ARCHITECTURE.md §9.3 for the write-up.
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = 'weekly_newsletter_digest'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func='newsletter.tasks.send_weekly_digest_issue',
        schedule_type='W',  # django_q.models.Schedule.WEEKLY
        repeats=-1,  # run forever, not a fixed number of times
        next_run=timezone.now(),
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('newsletter', '0003_newsletterissue_audience'),
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
