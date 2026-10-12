from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection

from articles.models import Article
from articles.search import refresh


class Command(BaseCommand):
    """Recompute every article's search text (articles/search.py) — after an
    import done straight into the database, or if search ever seems stale.

    It then asks MySQL to write its full-text cache to disk. A very large
    batch of changes can otherwise leave new rows missing from search until
    the server does that itself. This needs the SYSTEM_VARIABLES_ADMIN
    privilege; without it the step is skipped, with a note."""

    help = 'Rebuild Article.search_text for every article, then flush the full-text index.'

    def handle(self, *args, **options):
        ids = list(Article.objects.values_list('pk', flat=True))
        for start in range(0, len(ids), 200):
            refresh(ids[start:start + 200])
        self.stdout.write(self.style.SUCCESS(f'Rebuilt search text for {len(ids)} article(s).'))
        if connection.in_atomic_block:
            # OPTIMIZE TABLE commits implicitly — never inside someone's transaction.
            self.stdout.write('Inside a transaction — skipping the full-text flush.')
            return
        try:
            with connection.cursor() as cursor:
                cursor.execute('SET GLOBAL innodb_optimize_fulltext_only=ON')
                try:
                    cursor.execute('OPTIMIZE TABLE articles_article')
                    cursor.fetchall()
                finally:
                    cursor.execute('SET GLOBAL innodb_optimize_fulltext_only=OFF')
            self.stdout.write('Full-text index flushed.')
        except DatabaseError as exc:
            self.stdout.write(self.style.WARNING(f'Could not flush the full-text index ({exc}); it will catch up on its own.'))
