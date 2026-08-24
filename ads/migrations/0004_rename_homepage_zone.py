from django.db import migrations

# The old 'homepage' zone was split into distinct, size-labeled zones in
# migration 0003 (see ads/models.py Zone — "identify more ad sections" /
# "fix ad sizes" August 2026 rework). Any AdSlot rows created before this
# change would otherwise be orphaned: 'homepage' is no longer a valid zone
# value, so get_ad_for_zone() would never match them again and they'd
# silently stop showing. Map them to the closest equivalent new zone
# (Homepage Feed — Medium Rectangle) rather than leaving them stranded.


def rename_homepage_zone(apps, schema_editor):
    AdSlot = apps.get_model('ads', 'AdSlot')
    AdSlot.objects.filter(zone='homepage').update(zone='homepage_rectangle')


def reverse_rename_homepage_zone(apps, schema_editor):
    AdSlot = apps.get_model('ads', 'AdSlot')
    AdSlot.objects.filter(zone='homepage_rectangle').update(zone='homepage')


class Migration(migrations.Migration):

    dependencies = [
        ('ads', '0003_alter_adslot_image_alter_adslot_zone'),
    ]

    operations = [
        migrations.RunPython(rename_homepage_zone, reverse_rename_homepage_zone),
    ]
