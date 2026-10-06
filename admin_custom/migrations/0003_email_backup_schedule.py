# Nightly encrypted database backup email (ajna_health_lens/backups.py), 02:00.
import datetime

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = 'email_backup_daily'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if not Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        Schedule.objects.create(
            name=SCHEDULE_NAME, func='ajna_health_lens.backups.email_backup', schedule_type='D', repeats=-1,
            next_run=timezone.make_aware(datetime.datetime.combine(tomorrow, datetime.time(2, 0))),
        )


def delete_schedule(apps, schema_editor):
    apps.get_model('django_q', 'Schedule').objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('admin_custom', '0002_content_reports'),
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
