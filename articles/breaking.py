"""The current breaking-news stories for the site-wide banner.

Cached (BREAKING_CACHE_KEY, cleared on every Article.save()) so the banner
costs no query on most page views. Each cached entry keeps the story's own
breaking_until, so a story stops showing the moment that passes even if the
cache entry is still around.
"""
from django.core.cache import cache
from django.utils import timezone

from .models import BREAKING_CACHE_KEY, Article

CACHE_SECONDS = 300
# Cap so a busy news day doesn't push the page content below the fold.
MAX_STORIES = 3


def current_breaking() -> list[dict]:
    """[{'title', 'url', 'until', 'pk'}, ...] of live breaking stories, newest first."""
    entries = cache.get(BREAKING_CACHE_KEY)
    if entries is None:
        articles = Article.objects.filter(
            status=Article.Status.PUBLISHED, breaking_until__gt=timezone.now(),
        ).order_by('-published_at').only('pk', 'title', 'slug', 'breaking_until')[:MAX_STORIES]
        entries = [
            {'pk': a.pk, 'title': a.title, 'url': a.get_absolute_url(), 'until': a.breaking_until} for a in articles
        ]
        cache.set(BREAKING_CACHE_KEY, entries, CACHE_SECONDS)
    now = timezone.now()
    return [entry for entry in entries if entry['until'] > now]
