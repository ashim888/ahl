"""Gives every already-published article a published_at time. Where the
article was created on its publication day, that creation time is used (so
same-day stories keep a sensible order); otherwise the start of that day.
"""
import datetime

from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    Article = apps.get_model('articles', 'Article')
    for article in Article.objects.filter(publication_date__isnull=False, published_at__isnull=True):
        created_local = timezone.localtime(article.created_at) if article.created_at else None
        if created_local and created_local.date() == article.publication_date:
            published_at = article.created_at
        else:
            published_at = timezone.make_aware(datetime.datetime.combine(article.publication_date, datetime.time.min))
        Article.objects.filter(pk=article.pk).update(published_at=published_at)


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0035_publish_times_and_scheduling'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
