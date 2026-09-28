"""Gives every existing article one starting point in its history (its
current words, attributed to nobody), so the first real edit after this
change already has something to compare against."""
from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    Article = apps.get_model('articles', 'Article')
    ArticleRevision = apps.get_model('articles', 'ArticleRevision')
    for article in Article.objects.filter(revisions__isnull=True):
        ArticleRevision.objects.create(
            article=article, user=None, action='created', status=article.status,
            title=article.title, abstract=article.abstract or '', html_content=article.html_content or '',
            references=article.references or '', created_at=article.updated_at or timezone.now(),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0039_review_workflow_and_revisions'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
