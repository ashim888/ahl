"""Adds "Videos" to the main menu, linking to /videos/ (video stories,
articles.views.VideoListView) — a link-override entry like Training and
Issues. Placed just before Issues; editors can reorder or hide it from
/manage/sections/ like any other entry."""
from django.db import migrations
from django.db.models import F


def add_videos(apps, schema_editor):
    Section = apps.get_model('sections', 'Section')
    if Section.objects.filter(slug='videos').exists():
        return
    issues = Section.objects.filter(slug='issues', parent__isnull=True).first()
    order = issues.order if issues else (Section.objects.filter(parent__isnull=True).count())
    Section.objects.filter(parent__isnull=True, order__gte=order).update(order=F('order') + 1)
    Section.objects.create(
        slug='videos', name='Videos', name_en='Videos', name_ne='भिडियो',
        order=order, link_url_name='articles:video_list',
    )


def remove_videos(apps, schema_editor):
    apps.get_model('sections', 'Section').objects.filter(slug='videos', link_url_name='articles:video_list').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('sections', '0006_fill_nepali_section_names'),
        ('articles', '0045_article_video'),
    ]

    operations = [migrations.RunPython(add_videos, remove_videos)]
