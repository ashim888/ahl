# Performance: the ngram index on the whole search_text (title + body…) was
# slow for common words on long articles (huge bigram lists — ~2 s for a word
# in every article of 5,000). Article text now uses MySQL's word-based
# FULLTEXT parser (fast; handles Devanagari words and prefix* matches); the
# ngram index stays on the short title only, for type-ahead and 2-letter
# terms like "TB" (articles/search.py).
from django.db import migrations

FORWARD_SQL = [
    'ALTER TABLE articles_article DROP INDEX articles_article_search_ngram',
    'ALTER TABLE articles_article ADD FULLTEXT INDEX articles_article_search_words (search_text)',
]
REVERSE_SQL = [
    'ALTER TABLE articles_article DROP INDEX articles_article_search_words',
    'SET SESSION innodb_ft_enable_stopword=OFF',
    'ALTER TABLE articles_article ADD FULLTEXT INDEX articles_article_search_ngram (search_text) WITH PARSER ngram',
    'SET SESSION innodb_ft_enable_stopword=ON',
]


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0046_search_text'),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
