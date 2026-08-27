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


def breadcrumb_list_structured_data(items):
    """schema.org BreadcrumbList — powers the breadcrumb rich result in
    search listings. `items` is an ordered list of (name, url) tuples, home
    page first; the last item is the current page (url may be None for it,
    since schema.org doesn't require the current page to link to itself).
    """
    return ld_json({
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {
                '@type': 'ListItem',
                'position': position,
                'name': name,
                **({'item': url} if url else {}),
            }
            for position, (name, url) in enumerate(items, start=1)
        ],
    })


def person_structured_data(user, image_url):
    """schema.org Person — for a contributor's public byline page
    (AuthorDetailView). `sameAs` collects every external profile link the
    User model actually has (ORCID/LinkedIn/ResearchGate), omitting whichever
    ones this particular contributor hasn't filled in.
    """
    same_as = []
    if user.orcid:
        same_as.append(f'https://orcid.org/{user.orcid}')
    if user.linkedin_url:
        same_as.append(user.linkedin_url)
    if user.researchgate_url:
        same_as.append(user.researchgate_url)

    return ld_json({
        '@context': 'https://schema.org',
        '@type': 'Person',
        'name': user.get_full_name(),
        'description': user.bio or None,
        'affiliation': {'@type': 'Organization', 'name': user.affiliation} if user.affiliation else None,
        'image': image_url,
        'sameAs': same_as or None,
    })


def sitewide_structured_data(journal_name, logo_url, site_url, search_url):
    """schema.org NewsMediaOrganization + WebSite (with a SearchAction, the
    signal Google's sitelinks search box looks for) — emitted on every page
    (see ajna_health_lens/context_processors.py) rather than only the
    homepage; both types are safe to repeat sitewide and Google documents
    SearchAction discovery working either way.
    """
    organization_id = f'{site_url}#organization'
    return ld_json({
        '@context': 'https://schema.org',
        '@graph': [
            {
                '@type': 'NewsMediaOrganization',
                '@id': organization_id,
                'name': journal_name,
                'url': site_url,
                'logo': {'@type': 'ImageObject', 'url': logo_url},
            },
            {
                '@type': 'WebSite',
                '@id': f'{site_url}#website',
                'name': journal_name,
                'url': site_url,
                'publisher': {'@id': organization_id},
                'potentialAction': {
                    '@type': 'SearchAction',
                    'target': {'@type': 'EntryPoint', 'urlTemplate': f'{search_url}?q={{search_term_string}}'},
                    'query-input': 'required name=search_term_string',
                },
            },
        ],
    })


def news_article_structured_data(article, journal_name, canonical_url, image_url, publisher_logo_url, authors, keywords):
    """schema.org NewsArticle — powers rich results/Google News eligibility.
    `authors`/`keywords` are already-fetched lists (see ArticleDetailView),
    so this never issues its own query.
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
        # Access tiers landed in Phase 7 (billing app) — tells Google this is
        # legitimately gated content, not a thin/doorway page, so a
        # subscription article's abstract-only view (what an unauthenticated
        # crawler actually sees — see ArticleDetailView's show_full_text)
        # isn't penalized as low-quality. See billing/access.py.
        'isAccessibleForFree': article.access_type == article.AccessType.OPEN_ACCESS,
        'articleSection': article.get_article_type_display(),
        'keywords': ', '.join(kw.name for kw in keywords) or None,
    })
