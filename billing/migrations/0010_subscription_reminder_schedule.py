# Daily subscription expiry reminders (billing/reminders.py) on the qcluster
# worker — same Schedule pattern as 0008_verify_pending_payments_schedule.
import datetime

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = 'subscription_reminders_daily'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if not Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        # First run 08:00 tomorrow (site time), then daily at that time — a
        # morning email rather than whenever migrate happened to run.
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        first_run = timezone.make_aware(datetime.datetime.combine(tomorrow, datetime.time(8, 0)))
        Schedule.objects.create(
            name=SCHEDULE_NAME, func='billing.reminders.send_subscription_reminders',
            schedule_type='D', repeats=-1, next_run=first_run,
        )


def delete_schedule(apps, schema_editor):
    apps.get_model('django_q', 'Schedule').objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0009_ledger_vat_organizations'),
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
