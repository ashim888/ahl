from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ads', '0010_migrate_placeholder_flag_to_zones'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='adsettings',
            name='show_placeholder_when_empty',
        ),
    ]
