"""Background jobs for articles, run by the Django-Q worker (qcluster)."""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def publish_due_articles() -> int:
    """Publishes every Scheduled article whose time has come. Runs every
    minute (see migration 0037_publish_scheduled_schedule). Goes through
    Article.save() one by one — not a bulk update — so the homepage cache
    is cleared and the pitch "published" sync signal fires, exactly as if an
    editor had clicked Publish. Returns how many were published.
    """
    from .models import Article, ArticleRevision
    from .revisions import record_revision

    published = 0
    due = Article.objects.filter(status=Article.Status.SCHEDULED, published_at__lte=timezone.now())
    for article in due:
        article.status = Article.Status.PUBLISHED
        article.save()
        record_revision(article, None, ArticleRevision.Action.PUBLISHED)  # by the scheduler, not a person
        published += 1
        logger.info('Published scheduled article %s (%s)', article.pk, article.title)
    return published
