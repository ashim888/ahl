# Schedules sections.digest.send_topic_digests to run weekly via django_q's
# own Schedule model — the same worker process (`qcluster`) newsletter
# sends already require runs this automatically once this row exists, so
# there's no new deployment step (unlike backup.sh, which needs a real cron
# entry since it's outside Django entirely). First use of django_q.Schedule
# in this project — see ARCHITECTURE.md §4.2a for the write-up.
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = 'topic_digest_weekly'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func='sections.digest.send_topic_digests',
        schedule_type='W',  # django_q.models.Schedule.WEEKLY
        repeats=-1,  # run forever, not a fixed number of times
        next_run=timezone.now(),
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('sections', '0003_sectionfollow'),
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
