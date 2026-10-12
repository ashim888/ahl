"""Site search.

Each article keeps a plain-text `search_text` (title, summary, body,
keywords, authors, section names in English and Nepali — build_search_text)
with a word-based MySQL FULLTEXT index (migration 0047): fast even for
common words on a large archive, handles Devanagari words, and matches
word beginnings ("vacc" → vaccine). The title also has an **ngram** index
(0046) — used for type-ahead, to rank title matches first, and for
two-letter terms ("TB") that the word index skips (MySQL's minimum word
length is 3). Measured on 5,000 articles of 600 words: ~10 ms for a
typical term, ~85 ms for a word found in every article (vs 400 ms+ for the
old LIKE scan whenever a term is selective).

search_text is refreshed when an article is saved and when its keywords,
bylines, an author's name or a section's name change (articles/signals.py);
`manage.py rebuild_search_index` rebuilds every row.
"""
import difflib
import html
import re

from django.core.cache import cache
from django.db.models import Case, FloatField, IntegerField, Q, Value, When
from django.db.models.expressions import RawSQL
from django.utils.html import strip_tags

# Devanagari digits ०-९ → 0-9 in both the index and queries, so "२०८२" and
# "2082" find each other.
_DEVANAGARI_DIGITS = str.maketrans('०१२३४५६७८९', '0123456789')
# Characters with meaning in MySQL BOOLEAN MODE — stripped from user input.
_BOOLEAN_SPECIAL = re.compile(r'[+\-<>()~*"@]+')
RESULT_CACHE_SECONDS = 300
GENERATION_KEY = 'search:generation'


def normalize(text: str) -> str:
    return ' '.join(html.unescape(strip_tags(text or '')).translate(_DEVANAGARI_DIGITS).split())


def build_search_text(article) -> str:
    """Everything a reader might search an article by, as plain text."""
    parts = [article.title, article.abstract or '', article.html_content or '']
    if article.pk:
        parts += list(article.keyword_tags.values_list('name', flat=True))
        parts += [byline.display_name for byline in article.articleauthor_set.select_related('author')]
    if article.section_id:
        section = article.section
        parts += [getattr(section, 'name_en', '') or section.name, getattr(section, 'name_ne', '') or '']
    return normalize(' '.join(part for part in parts if part))


def refresh(article_ids) -> None:
    """Recompute search_text for these articles (a queryset update — no
    save() signals, no last-modified churn) and invalidate cached results."""
    from .models import Article

    for article in Article.objects.filter(pk__in=list(article_ids)).select_related('section'):
        Article.objects.filter(pk=article.pk).update(search_text=build_search_text(article))
    bump_generation()


def bump_generation():
    """Cached search results are keyed on this counter, so any change to
    the searchable content makes old results unreachable at once."""
    try:
        cache.incr(GENERATION_KEY)
    except ValueError:
        cache.set(GENERATION_KEY, 1, None)


def terms(query: str) -> list[str]:
    """The usable words of a query (2+ characters — the ngram size)."""
    cleaned = _BOOLEAN_SPECIAL.sub(' ', normalize(query))
    return [word for word in cleaned.split() if len(word) >= 2][:12]


def _title_ngram(words):
    expression = ' '.join(f'+{word}' for word in words)
    return RawSQL('MATCH(articles_article.title) AGAINST (%s IN BOOLEAN MODE)', (expression,), output_field=FloatField())


def search_ids(queryset, query: str, *, newest: bool = False, limit: int = 500) -> list[int]:
    """Ids of the articles in `queryset` matching every word of `query`,
    best first (title matches, then relevance, then newest) or newest first."""
    words = terms(query)
    long_words = [word for word in words if len(word) >= 3]
    short_words = [word for word in words if len(word) < 3]
    ids = []
    if long_words:
        expression = ' '.join(f'+{word}*' for word in long_words)
        body = RawSQL('MATCH(articles_article.search_text) AGAINST (%s IN BOOLEAN MODE)', (expression,), output_field=FloatField())
        matches = queryset.annotate(body_score=body).filter(body_score__gt=0)
        for word in short_words:  # cheap: only scans what the index already narrowed down
            matches = matches.filter(search_text__icontains=word)
        if newest:
            ids = list(matches.order_by('-published_at').values_list('pk', flat=True)[:limit])
        else:
            ids = list(matches.order_by('-body_score', '-published_at').values_list('pk', flat=True)[:limit])
            # Title matches first. Looked up separately through the title
            # index — cheaper than scoring every row's title (measured).
            in_title = set(queryset.annotate(title_score=_title_ngram(words)).filter(title_score__gt=0)
                           .values_list('pk', flat=True)[:1000])
            ids = [pk for pk in ids if pk in in_title] + [pk for pk in ids if pk not in in_title]
    elif short_words:
        matches = queryset.annotate(title_score=_title_ngram(short_words)).filter(title_score__gt=0)
        ids = list(matches.order_by('-published_at' if newest else '-title_score', '-published_at').values_list('pk', flat=True)[:limit])
    if ids:
        return ids
    # Fallback — the indexes found nothing: every word as a plain substring.
    # Covers rows MySQL hasn't indexed yet (only committed rows are), one-
    # letter words and 2-letter words only in the body. Rare, so the slower
    # scan is acceptable here.
    matching = queryset
    for word in words or [normalize(query)]:
        matching = matching.filter(search_text__icontains=word)
    in_title = Q()
    for word in words or [normalize(query)]:
        in_title &= Q(title__icontains=word)
    matching = matching.annotate(title_hit=Case(When(in_title, then=0), default=1, output_field=IntegerField()))
    order = ('-published_at',) if newest else ('title_hit', '-published_at')
    return list(matching.order_by(*order).values_list('pk', flat=True)[:limit])


def cached_ids(cache_key_parts: tuple, compute) -> list[int]:
    """Result ids for a search (compute() returns them), cached for a few
    minutes and dropped as soon as any article changes (bump_generation)."""
    import hashlib

    generation = cache.get(GENERATION_KEY) or 0
    digest = hashlib.sha256(repr((generation,) + cache_key_parts).encode()).hexdigest()[:32]
    key = f'search:ids:{digest}'
    ids = cache.get(key)
    if ids is None:
        ids = compute()
        cache.set(key, ids, RESULT_CACHE_SECONDS)
    return ids


def snippet(article, query: str, length: int = 220) -> str:
    """A short excerpt around the first matching word, with matches in
    <mark>. Paid articles only ever show their public summary — never the
    paywalled body."""
    from django.utils.safestring import mark_safe

    words = terms(query)
    if article.access_type == article.AccessType.OPEN_ACCESS:
        text = normalize(article.html_content) or normalize(article.abstract)
    else:
        text = normalize(article.summary)
    if not text:
        return ''
    lowered = text.lower()
    positions = [lowered.find(word.lower()) for word in words if lowered.find(word.lower()) >= 0]
    start = max(min(positions) - 60, 0) if positions else 0
    excerpt = text[start:start + length]
    excerpt = ('… ' if start else '') + html.escape(excerpt) + (' …' if start + length < len(text) else '')
    for word in sorted(set(words), key=len, reverse=True):
        excerpt = re.sub(f'({re.escape(html.escape(word))})', r'<mark>\1</mark>', excerpt, flags=re.IGNORECASE)
    return mark_safe(excerpt)


def did_you_mean(query: str) -> str:
    """For a search with no results: the closest keyword or section name to
    each word, if any is close — 'maleria' → 'malaria'."""
    from sections.models import Section

    from .models import Keyword

    vocabulary = {name.lower() for name in Keyword.objects.values_list('name', flat=True)}
    vocabulary |= {name.lower() for name in Section.objects.values_list('name', flat=True) if name}
    for keyword_name in list(vocabulary):
        vocabulary.update(keyword_name.split())
    suggestion, changed = [], False
    for word in normalize(query).split():
        match = difflib.get_close_matches(word.lower(), vocabulary, n=1, cutoff=0.75)
        if match and match[0] != word.lower():
            suggestion.append(match[0])
            changed = True
        else:
            suggestion.append(word)
    return ' '.join(suggestion) if changed else ''


def suggestions(query: str, limit: int = 6):
    """Type-ahead: the best title matches for what's typed so far (ngram
    index, so a half-typed word already matches), else body matches."""
    from .models import Article

    published = Article.objects.filter(status=Article.Status.PUBLISHED)
    words = terms(query)
    if words:
        found = list(published.annotate(score=_title_ngram(words)).filter(score__gt=0).select_related('section')
                     .order_by('-score', '-published_at')[:limit])
        if found:
            return found
    ids = search_ids(published, query, limit=limit)
    by_id = {article.pk: article for article in Article.objects.filter(pk__in=ids).select_related('section')}
    return [by_id[pk] for pk in ids if pk in by_id]
