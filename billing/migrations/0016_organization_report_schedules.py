# Organization usage reports (billing/org_reports.py) on the qcluster worker:
# last month's report on the 1st at 07:00, renewal reminders daily at 08:30.
import datetime

from django.db import migrations
from django.utils import timezone

MONTHLY = 'organization_usage_reports_monthly'
DAILY = 'organization_renewal_reminders_daily'


def create_schedules(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    today = timezone.localdate()
    if not Schedule.objects.filter(name=MONTHLY).exists():
        first_of_next = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
        Schedule.objects.create(
            name=MONTHLY, func='billing.org_reports.send_monthly_reports', schedule_type='M', repeats=-1,
            next_run=timezone.make_aware(datetime.datetime.combine(first_of_next, datetime.time(7, 0))),
        )
    if not Schedule.objects.filter(name=DAILY).exists():
        tomorrow = today + datetime.timedelta(days=1)
        Schedule.objects.create(
            name=DAILY, func='billing.org_reports.send_renewal_reminders', schedule_type='D', repeats=-1,
            next_run=timezone.make_aware(datetime.datetime.combine(tomorrow, datetime.time(8, 30))),
        )


def delete_schedules(apps, schema_editor):
    apps.get_model('django_q', 'Schedule').objects.filter(name__in=[MONTHLY, DAILY]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0015_organization_usage'),
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedules, delete_schedules),
    ]
