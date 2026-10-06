"""Topics: the reader-facing side of Keyword — every tag is a "#hashtag"
with its own page (/topics/<slug>/), listed at /topics/, shown on article
pages and cards, and in a "Trending" strip on the homepage.

Only keywords with at least one published article are public; a keyword
used only on drafts is a 404, so unpublished work never leaks through its
tags. Topic pages with fewer than INDEX_MIN_ARTICLES stories are noindex
(thin pages hurt a site's search ranking).
"""
import datetime
import re

from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from .models import Article, Keyword

INDEX_MIN_ARTICLES = 2
TRENDING_DAYS = 30
TRENDING_CACHE_SECONDS = 600

_PUBLISHED = Q(articles__status=Article.Status.PUBLISHED)


def hashtag(name: str) -> str:
    """'Type 2 Diabetes' → '#Type2Diabetes'; 'मानसिक स्वास्थ्य' →
    '#मानसिक_स्वास्थ्य' (how Nepali hashtags are written); 'HIV' → '#HIV'."""
    words = [w for w in re.split(r'[\s\-_/]+', (name or '').strip()) if w]
    if not words:
        return ''
    if all(w.isascii() for w in words):
        return '#' + ''.join(w if w.isupper() else w[:1].upper() + w[1:] for w in words)
    return '#' + '_'.join(words)


def public_topics():
    """Keywords on at least one published article, with that count."""
    return Keyword.objects.annotate(article_count=Count('articles', filter=_PUBLISHED, distinct=True)).filter(
        article_count__gt=0,
    )


def trending_topics(limit: int = 12) -> list:
    """Most-used topics on stories published in the last TRENDING_DAYS days,
    falling back to the most-used overall when there's little recent news."""
    def load():
        since = timezone.now() - datetime.timedelta(days=TRENDING_DAYS)
        recent = list(
            Keyword.objects.annotate(recent=Count('articles', filter=_PUBLISHED & Q(articles__published_at__gte=since),
                                                  distinct=True))
            .filter(recent__gt=0).order_by('-recent', 'name')[:limit],
        )
        if len(recent) < limit:
            taken = {k.pk for k in recent}
            recent += [k for k in public_topics().order_by('-article_count', 'name')[:limit * 2] if k.pk not in taken][
                :limit - len(recent)]
        return recent

    return cache.get_or_set(f'topics:trending:{limit}', load, TRENDING_CACHE_SECONDS)


def related_topics(keyword: Keyword, limit: int = 10) -> list:
    """Topics most often tagged on the same published stories."""
    article_ids = Article.objects.filter(status=Article.Status.PUBLISHED, keyword_tags=keyword).values('pk')
    return list(
        Keyword.objects.filter(articles__in=article_ids).exclude(pk=keyword.pk)
        .annotate(shared=Count('articles', distinct=True)).order_by('-shared', 'name')[:limit],
    )
