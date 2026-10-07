# Featured images with no description get the slug's words (articles/slugs.py
# alt_from_slug), the same default new articles get on save.
from django.db import migrations


def fill(apps, schema_editor):
    from articles.slugs import alt_from_slug

    Article = apps.get_model('articles', 'Article')
    for article in Article.objects.exclude(featured_image='').exclude(featured_image__isnull=True).filter(
            featured_image_alt='').only('pk', 'slug'):
        Article.objects.filter(pk=article.pk).update(featured_image_alt=alt_from_slug(article.slug))


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0051_featured_image_size_without_width_field'),
    ]

    operations = [
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
