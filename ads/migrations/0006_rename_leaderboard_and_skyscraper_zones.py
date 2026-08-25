from django.db import migrations

# Two zones were resized in 0005 (see ads/models.py Zone — "give the ad room"
# sizing rework): the old 300×600 Half Page became a 728×90 Leaderboard, and
# the old 160×600 Wide Skyscraper became a 300×600 Half Page. Both got a new
# value string along with their new label, since the old ones now describe
# the wrong shape entirely — same reasoning as migration 0004. Remap any
# AdSlot rows already sold under the old zone values rather than orphaning
# them (get_ad_for_zone would otherwise never match them again). Any
# creative already uploaded under these zones will still need re-uploading
# to the new required size — that part can't be fixed by a migration.


def rename_zones(apps, schema_editor):
    AdSlot = apps.get_model('ads', 'AdSlot')
    AdSlot.objects.filter(zone='homepage_half_page').update(zone='homepage_leaderboard')
    AdSlot.objects.filter(zone='article_skyscraper').update(zone='article_sidebar_half_page')


def reverse_rename_zones(apps, schema_editor):
    AdSlot = apps.get_model('ads', 'AdSlot')
    AdSlot.objects.filter(zone='homepage_leaderboard').update(zone='homepage_half_page')
    AdSlot.objects.filter(zone='article_sidebar_half_page').update(zone='article_skyscraper')


class Migration(migrations.Migration):

    dependencies = [
        ('ads', '0005_alter_adslot_zone'),
    ]

    operations = [
        migrations.RunPython(rename_zones, reverse_rename_zones),
    ]
