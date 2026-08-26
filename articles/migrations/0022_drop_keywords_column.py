from django.db import migrations

# Finishes what 0020/0021 started: 0020 added Keyword/keyword_tags without
# touching the old `keywords` CharField yet, 0021 copied its data into real
# Keyword rows. This migration rebuilds the FULLTEXT index to drop the
# `keywords` column (it's moving off this table entirely, onto Keyword via
# keyword_tags — see articles/views.py SearchView, which now matches
# keyword_tags__name__icontains alongside the FULLTEXT match instead) and
# then removes the column itself. The index has to be rebuilt *before* the
# column is dropped — an index can't reference a column that's gone.


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0021_convert_keywords_to_keyword_rows'),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'ALTER TABLE articles_article DROP INDEX articles_article_fulltext, '
                'ADD FULLTEXT INDEX articles_article_fulltext (title, abstract)'
            ),
            reverse_sql=(
                'ALTER TABLE articles_article DROP INDEX articles_article_fulltext, '
                'ADD FULLTEXT INDEX articles_article_fulltext (title, abstract, keywords)'
            ),
        ),
        migrations.RemoveField(
            model_name='article',
            name='keywords',
        ),
    ]
