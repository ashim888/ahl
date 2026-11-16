"""Adds "Health Library" to the main menu, linking to /library/ (library
app) — a link-override entry like Training, Videos and Issues, placed after
them. Created hidden (is_active=False) so the menu doesn't send readers to
an empty library: switch it on in /manage/sections/ once there are documents
in it."""
from django.db import migrations
from django.db.models import Max


def add_library(apps, schema_editor):
    Section = apps.get_model('sections', 'Section')
    if Section.objects.filter(slug='library').exists() or Section.objects.filter(
            link_url_name='library:resource_list').exists():
        return
    last = Section.objects.filter(parent__isnull=True).aggregate(m=Max('order'))['m'] or 0
    Section.objects.create(
        slug='library', name='Health Library', name_en='Health Library', name_ne='स्वास्थ्य पुस्तकालय',
        order=last + 1, link_url_name='library:resource_list', is_active=False,
    )


def remove_library(apps, schema_editor):
    apps.get_model('sections', 'Section').objects.filter(slug='library', link_url_name='library:resource_list').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('sections', '0007_videos_nav_entry'),
        ('library', '0001_initial'),
    ]

    operations = [migrations.RunPython(add_library, remove_library)]
