"""The current breaking-news story for the site-wide banner.

Cached (BREAKING_CACHE_KEY, cleared on every Article.save()) so the banner
costs no query on most page views. The cached entry keeps the story's own
breaking_until, so it stops showing the moment that passes even if the cache
entry is still around.
"""
from django.core.cache import cache
from django.utils import timezone

from .models import BREAKING_CACHE_KEY, Article

CACHE_SECONDS = 300
_NONE = 'none'


def current_breaking() -> dict | None:
    """{'title', 'url', 'until', 'pk'} of the newest live breaking story, or None."""
    entry = cache.get(BREAKING_CACHE_KEY)
    if entry is None:
        article = Article.objects.filter(
            status=Article.Status.PUBLISHED, breaking_until__gt=timezone.now(),
        ).order_by('-published_at').only('pk', 'title', 'slug', 'breaking_until').first()
        entry = _NONE if article is None else {
            'pk': article.pk, 'title': article.title, 'url': article.get_absolute_url(), 'until': article.breaking_until,
        }
        cache.set(BREAKING_CACHE_KEY, entry, CACHE_SECONDS)
    if entry == _NONE or entry['until'] <= timezone.now():
        return None
    return entry
