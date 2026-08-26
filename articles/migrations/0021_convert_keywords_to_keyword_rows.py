from django.db import migrations
from django.utils.text import slugify

# Splits every Article's old comma-separated `keywords` string into real
# Keyword rows (deduped by slug — "Diabetes" and "diabetes" fold into one
# row) and links them via the new keyword_tags M2M. Runs after 0020 added
# keyword_tags but before 0022 removes the old `keywords` column, so both
# fields are still present on the historical model here. See Keyword's
# docstring in articles/models.py.


def convert_keywords(apps, schema_editor):
    Article = apps.get_model('articles', 'Article')
    Keyword = apps.get_model('articles', 'Keyword')

    slug_to_keyword = {}
    for article in Article.objects.exclude(keywords__isnull=True).exclude(keywords=''):
        keyword_ids = []
        for raw_name in article.keywords.split(','):
            name = raw_name.strip()
            if not name:
                continue
            slug = slugify(name)
            if not slug:
                continue
            keyword = slug_to_keyword.get(slug)
            if keyword is None:
                keyword, _created = Keyword.objects.get_or_create(slug=slug, defaults={'name': name})
                slug_to_keyword[slug] = keyword
            if keyword.id not in keyword_ids:
                keyword_ids.append(keyword.id)
        if keyword_ids:
            article.keyword_tags.set(keyword_ids)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0020_keyword_remove_article_keywords_article_keyword_tags'),
    ]

    operations = [
        migrations.RunPython(convert_keywords, noop),
    ]
