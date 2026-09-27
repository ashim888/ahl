"""Deletes old first-party analytics events so their tables don't grow
forever: articles.ArticleView (one row per counted page view),
articles.KeywordEvent (one row per keyword per counted view, plus clicks)
and ads.AdEvent (one row per ad impression/click).

Only the raw event logs are pruned. Running totals that live on the parent
rows — AdSlot.impression_count/click_count, Article.download_count — are
untouched, so the ads list and lifetime figures stay correct. Every
dashboard reads at most 90 days of events (Trending: 7, analytics pages:
7–90), so the default retention of 400 days keeps a full year for
year-on-year comparisons with room to spare.

Runs daily via a Django-Q schedule (migration 0001_analytics_retention_schedule);
`python manage.py prune_analytics_events` runs it by hand.
"""
import datetime
import logging

from django.conf import settings
from django.utils import timezone

from ads.models import AdEvent
from articles.models import ArticleView, KeywordEvent

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 400
BATCH_SIZE = 5000

# (model, timestamp field) for every pruned event log.
EVENT_TABLES = [
    (ArticleView, 'viewed_at'),
    (KeywordEvent, 'occurred_at'),
    (AdEvent, 'occurred_at'),
]


def retention_days() -> int:
    return int(getattr(settings, 'ANALYTICS_RETENTION_DAYS', DEFAULT_RETENTION_DAYS))


def prune_analytics_events(days: int | None = None) -> dict[str, int]:
    """Deletes events older than `days` (default: ANALYTICS_RETENTION_DAYS),
    in batches of BATCH_SIZE so no single DELETE holds long locks on a busy
    table. Returns {model name: rows deleted}.
    """
    days = days or retention_days()
    cutoff = timezone.now() - datetime.timedelta(days=days)
    deleted = {}
    for model, field in EVENT_TABLES:
        total = 0
        while True:
            ids = list(
                model.objects.filter(**{f'{field}__lt': cutoff}).values_list('pk', flat=True)[:BATCH_SIZE],
            )
            if not ids:
                break
            total += model.objects.filter(pk__in=ids).delete()[0]
        deleted[model.__name__] = total
    logger.info('Pruned analytics events older than %s days: %s', days, deleted)
    return deleted
