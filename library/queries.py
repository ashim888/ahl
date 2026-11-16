"""Library lookups shared by /library/, site search, article pages and topic
pages. The library is small (hundreds of documents, not tens of thousands of
articles), so plain word matching is enough; no full-text index needed."""
from django.db.models import Q

from .models import Resource


def published():
    return Resource.objects.filter(is_published=True)


def matching(queryset, query: str):
    """Resources in `queryset` where every word of `query` appears in the
    title, summary, publisher or a topic name, in any order. Words are cleaned
    the same way as site search (articles/search.py), so "२०८१" finds "2081"."""
    from articles.search import normalize, terms

    words = terms(query) or [normalize(query)]
    for word in words:
        if not word:
            continue
        queryset = queryset.filter(
            Q(title__icontains=word) | Q(summary__icontains=word) | Q(source__icontains=word)
            | Q(keyword_tags__name__icontains=word)
        )
    return queryset.distinct()


def search(query: str, limit: int = 3):
    """(best matches, total) for site search: title matches first, then newest."""
    found = matching(published(), query)
    total = found.count()
    if not total:
        return [], 0
    from articles.search import terms

    words = terms(query)
    title_hit = Q()
    for word in words:
        title_hit &= Q(title__icontains=word)
    in_title = list(found.filter(title_hit).order_by('-created_at')[:limit]) if words else []
    rest = list(found.exclude(pk__in=[r.pk for r in in_title]).order_by('-created_at')[:limit - len(in_title)])
    return in_title + rest, total


def for_article(article, limit: int = 4):
    """Documents an editor linked to this article (Resource.related_articles).
    Explicit links only: topic matching is too loose here ("Nepal" would pull
    in half the library)."""
    if not article.pk:
        return []
    return list(published().filter(related_articles=article).order_by('-created_at')[:limit])


def glossary_matching(queryset, query: str, *, definitions: bool = True):
    """Glossary terms where every word of `query` is in a name, an alias or
    (with `definitions`) a definition."""
    from articles.search import normalize, terms

    for word in terms(query) or [normalize(query)]:
        if not word:
            continue
        hit = Q(term_ne__icontains=word) | Q(term_en__icontains=word) | Q(also_called__icontains=word)
        if definitions:
            hit |= Q(definition_ne__icontains=word) | Q(definition_en__icontains=word)
        queryset = queryset.filter(hit)
    return queryset


def glossary_for_search(query: str, limit: int = 2):
    """Terms whose *name* matches, for the site search page: someone typing
    "HbA1c" or "मधुमेह" should see what it means before the articles."""
    from .models import GlossaryTerm

    query = query.strip()
    if len(query) < 2:
        return []
    return list(glossary_matching(GlossaryTerm.objects.filter(is_published=True), query, definitions=False)[:limit])


def for_topic(keyword, limit: int = 4):
    """(newest documents tagged with this topic, total)."""
    tagged = published().filter(keyword_tags=keyword)
    total = tagged.count()
    return (list(tagged.order_by('-created_at')[:limit]) if total else []), total
