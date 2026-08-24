from django.db import migrations

# MySQL-specific FULLTEXT index (InnoDB has supported FULLTEXT since 5.6, and
# this project targets MySQL 8.0 — see CLAUDE.md). Django has no cross-database
# FULLTEXT index type, hence RunSQL rather than a Meta.indexes entry.
# Powers articles/views.py SearchView's MATCH ... AGAINST query — a real
# indexed, word-based search instead of the previous icontains-only scan
# (see ROADMAP.md Phase 9, "still-open" full-text search gap, now closed).


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0014_articleview'),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'ALTER TABLE articles_article '
                'ADD FULLTEXT INDEX articles_article_fulltext (title, abstract, keywords)'
            ),
            reverse_sql='ALTER TABLE articles_article DROP INDEX articles_article_fulltext',
        ),
    ]
