# Rebuild the search FULLTEXT indexes without MySQL's stopword list.
#
# 0050 added columns to articles_article; MySQL rebuilt the table and its
# FULLTEXT indexes with the session's default stopword list ON, which broke
# the title ngram index (chunks containing "a", "is"… dropped — "malaria"
# stopped matching titles). settings.DATABASES now turns stopwords off on
# every connection so this can't recur; this repairs databases that already
# ran 0050. Then flush the index cache (rebuild_search_index does the same).
from django.db import migrations

FORWARD = [
    'SET SESSION innodb_ft_enable_stopword=OFF',
    'ALTER TABLE articles_article DROP INDEX articles_article_title_ngram',
    'ALTER TABLE articles_article ADD FULLTEXT INDEX articles_article_title_ngram (title) WITH PARSER ngram',
    'ALTER TABLE articles_article DROP INDEX articles_article_search_words',
    'ALTER TABLE articles_article ADD FULLTEXT INDEX articles_article_search_words (search_text)',
    # Freshly built FULLTEXT indexes don't see the next new row until they're
    # synced once (measured: the first article saved afterwards wasn't found
    # by title). A full OPTIMIZE needs no extra privileges; the table is small.
    'OPTIMIZE TABLE articles_article',
]


def rebuild(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    with schema_editor.connection.cursor() as cursor:
        for statement in FORWARD:
            cursor.execute(statement)
            if statement.startswith('OPTIMIZE'):
                cursor.fetchall()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('articles', '0052_featured_image_alt_from_slug'),
    ]

    operations = [
        migrations.RunPython(rebuild, migrations.RunPython.noop),
    ]
