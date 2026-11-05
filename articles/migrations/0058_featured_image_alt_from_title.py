# Featured images whose description is still the automatic slug-based one
# (0052, articles/slugs.py alt_from_slug) get the headline instead — the
# default new articles now get on save. A Nepali headline's slug is
# romanized, which a screen reader reads out as noise. Descriptions an
# editor wrote themselves are left alone.
from django.db import migrations, models


def fill(apps, schema_editor):
    from articles.slugs import alt_from_slug

    Article = apps.get_model('articles', 'Article')
    for article in Article.objects.exclude(featured_image='').exclude(featured_image__isnull=True).only(
            'pk', 'slug', 'title', 'featured_image_alt'):
        if article.featured_image_alt == alt_from_slug(article.slug) and article.title:
            Article.objects.filter(pk=article.pk).update(featured_image_alt=article.title[:250])


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0057_articleview_viewed_at_index'),
    ]

    operations = [
        migrations.AlterField(
            model_name='article',
            name='featured_image_alt',
            field=models.CharField(blank=True, help_text='What the image shows, for screen readers and search engines. Filled from the headline when left empty.', max_length=250, verbose_name='Image description (alt text)'),
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
