# Worker heartbeat every 5 minutes (ajna_health_lens/health.py) — proves the
# qcluster worker is alive to /healthz/ and `manage.py check_health`.
from django.db import migrations

SCHEDULE_NAME = 'worker_heartbeat'


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model('django_q', 'Schedule')
    if not Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        Schedule.objects.create(
            name=SCHEDULE_NAME, func='ajna_health_lens.health.worker_heartbeat', schedule_type='I', minutes=5, repeats=-1,
        )


def delete_schedule(apps, schema_editor):
    apps.get_model('django_q', 'Schedule').objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('admin_custom', '0003_email_backup_schedule'),
        ('django_q', '0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more'),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
