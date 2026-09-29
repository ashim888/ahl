# Settles Fonepay payments whose reader paid but closed the page before it
# confirmed — runs billing.payments.verify_pending_payments every 5 minutes
# on the qcluster worker (same Schedule pattern as the other jobs).
from django.db import migrations

SCHEDULE_NAME = 'verify_pending_payments'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if not Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        Schedule.objects.create(
            name=SCHEDULE_NAME, func='billing.payments.verify_pending_payments',
            schedule_type='I', minutes=5, repeats=-1,
        )


def delete_schedule(apps, schema_editor):
    apps.get_model('django_q', 'Schedule').objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0007_payments'),
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
