# Performance: the ngram index on the whole search_text (title + body…) was
# slow for common words on long articles (huge bigram lists — ~2 s for a word
# in every article of 5,000). Article text uses a word-based FULLTEXT index
# (fast; handles Devanagari words and prefix* matches); the ngram index stays
# on the short title only, for type-ahead and 2-letter terms like "TB"
# (articles/search.py). Safe to run again, and works on MariaDB — see
# articles/fulltext.py.
from django.db import migrations

from articles import fulltext


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    with schema_editor.connection.cursor() as cursor:
        fulltext.drop_indexes(cursor, ['articles_article_search_ngram'])
        fulltext.add_words_index(cursor)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    with schema_editor.connection.cursor() as cursor:
        fulltext.drop_indexes(cursor, [fulltext.WORDS_INDEX])


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0046_search_text'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
