# Daily privacy clean-up (users/privacy.py privacy_housekeeping): clears old
# comment IP addresses, login-attempt records, unconfirmed newsletter
# sign-ups and expired sessions — the retention periods the Privacy policy
# promises. Same Schedule pattern as the other qcluster jobs.
import datetime

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = 'privacy_housekeeping_daily'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if not Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        Schedule.objects.create(
            name=SCHEDULE_NAME, func='users.privacy.privacy_housekeeping', schedule_type='D', repeats=-1,
            next_run=timezone.make_aware(datetime.datetime.combine(tomorrow, datetime.time(3, 30))),
        )


def delete_schedule(apps, schema_editor):
    apps.get_model('django_q', 'Schedule').objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0009_privacy_preferences'),
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
