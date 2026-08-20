"""Structured-data helper shared by ArticleDetailView. A standalone module
(not inlined in views.py) since sitemaps.py/feeds.py live alongside it for
the same reason — SEO/distribution concerns kept out of the main view logic.
"""
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.utils.safestring import mark_safe

# Mirrors Django's own json_script escaping (django.utils.html) — safe to
# inline inside a <script> tag even if a title/abstract happens to contain
# "</script>", "-->", or similar.
_JSON_LD_ESCAPES = {
    ord('>'): '\\u003E',
    ord('<'): '\\u003C',
    ord('&'): '\\u0026',
}


def ld_json(data):
    """Render a dict as a safe JSON-LD payload for a
    <script type="application/ld+json"> tag — not django.utils.html.json_script,
    which hardcodes type="application/json" (fine for app data, wrong
    mime/spec for search-engine structured data).
    """
    cleaned = {k: v for k, v in data.items() if v is not None}
    return mark_safe(json.dumps(cleaned, cls=DjangoJSONEncoder).translate(_JSON_LD_ESCAPES))


def news_article_structured_data(article, journal_name, canonical_url, image_url, publisher_logo_url, authors):
    """schema.org NewsArticle — powers rich results/Google News eligibility.
    `authors` is the already-fetched list of ArticleAuthor rows (see
    ArticleDetailView), so this never issues its own query.
    """
    return ld_json({
        '@context': 'https://schema.org',
        '@type': 'NewsArticle',
        'headline': article.title[:110],
        'description': article.abstract,
        'image': [image_url] if image_url else None,
        'datePublished': article.publication_date.isoformat() if article.publication_date else None,
        'dateModified': article.updated_at.isoformat(),
        'mainEntityOfPage': {'@type': 'WebPage', '@id': canonical_url},
        'author': [
            {'@type': 'Person', 'name': aa.user.get_full_name()} for aa in authors
        ] or [{'@type': 'Organization', 'name': journal_name}],
        'publisher': {
            '@type': 'Organization',
            'name': journal_name,
            'logo': {'@type': 'ImageObject', 'url': publisher_logo_url},
        },
    })
