"""Marks health-glossary terms in an article's text, so a reader can tap a
word and see what it means (static/js/citations.js; the glossary itself is
library.GlossaryTerm).

Applied at render time, like citations (articles/citations.py), so the
stored article HTML stays exactly as the editor wrote it. Rules:

- each term at most once per article (its first appearance), at most
  MAX_MARKS terms, so the text doesn't turn into a page of underlines;
- never inside links, headings, code, captions, citations, buttons or table
  headers;
- Nepali names match with common endings attached ("मधुमेहको", "खोपहरू")
  but never inside a longer word ("खोप" doesn't match "खोपडी");
- English names match whole words, any case; ALL-CAPS names ("DM", "WHO")
  only in capitals, so "who" the pronoun is left alone.

Without JavaScript a marked term is a plain link to its glossary page.
"""
import html as html_lib
import re

from django.core.cache import cache
from django.urls import reverse

MAX_MARKS = 12
CACHE_KEY = 'glossary:marking-index:v1'
SKIP_TAGS = {'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'code', 'pre', 'script', 'style', 'sup', 'sub', 'button',
             'figcaption', 'th', 'dfn', 'abbr', 'label', 'select', 'option', 'textarea', 'mark'}
_DEVANAGARI = re.compile(r'[ऀ-ॿ]')
# Devanagari letters and signs only — the block also holds the full stops ।/॥
# (U+0964–5) and the digits ०-९ (U+0966–F), which end a word, not continue it.
_NE_LETTER = r'[ऀ-ॣ॰-ॿ]'
# What may follow a Nepali term inside the same word: an optional plural, then
# an optional postposition or particle. Anything else means it's a different word.
_NE_SUFFIX = (r'(?:हरू)?(?:को|का|की|मा|ले|लाई|बाट|सँग|संग|सम्म|भन्दा|तिर|देखि|मै|नै|लगायत|जस्ता|जस्तो)?'
              rf'(?:मा|को|ले|नै)?(?!{_NE_LETTER})')
_TAG = re.compile(r'(<[^>]*>)')
_TAG_NAME = re.compile(r'^<\s*(/?)\s*([a-zA-Z0-9]+)')


def clear_cache(**kwargs):
    """Signal receiver (library/apps.py): a term was saved or deleted."""
    cache.delete(CACHE_KEY)
    _compiled.clear()


def _entries():
    """[(name, slug, kind)] for every published term — kind is 'ne', 'en' or
    'caps'. Cached until a term changes."""
    entries = cache.get(CACHE_KEY)
    if entries is None:
        from .models import GlossaryTerm

        entries = []
        for term in GlossaryTerm.objects.filter(is_published=True).only('term_ne', 'term_en', 'also_called', 'slug'):
            for name in term.names:
                name = name.strip()
                if len(name) < 2:
                    continue
                if _DEVANAGARI.search(name):
                    kind = 'ne'
                elif name.isupper():
                    kind = 'caps'  # DM, WHO, TB: exact case only
                else:
                    kind = 'en'
                entries.append((name, term.slug, kind))
        cache.set(CACHE_KEY, entries, 60 * 60 * 24)
    return entries


_compiled = {}


def _matcher():
    """(regex, lookup) built from the current entries; rebuilt only when they change."""
    entries = _entries()
    key = hash(tuple(entries))
    if key in _compiled:
        return _compiled[key]
    _compiled.clear()
    if not entries:
        _compiled[key] = (None, {})
        return _compiled[key]

    def alternation(kind):
        names = sorted({n for n, _, k in entries if k == kind}, key=len, reverse=True)
        return '|'.join(re.escape(n) for n in names)

    parts = []
    if ne := alternation('ne'):
        parts.append(rf'(?<!{_NE_LETTER})(?P<ne>{ne})(?={_NE_SUFFIX})')
    if en := alternation('en'):
        parts.append(rf'(?<![\w-])(?i:(?P<en>{en}))(?![\w-])')
    if caps := alternation('caps'):
        parts.append(rf'(?<![\w-])(?P<caps>{caps})(?![\w-])')
    lookup = {}
    for name, slug, kind in entries:
        lookup.setdefault((kind, name.lower() if kind == 'en' else name), slug)
    _compiled[key] = (re.compile('|'.join(parts)), lookup)
    return _compiled[key]


def mark_terms(html: str, max_marks: int = MAX_MARKS):
    """(html with terms marked, [slugs used, in order of appearance])."""
    if not html:
        return html, []
    regex, lookup = _matcher()
    if regex is None:
        return html, []
    used = []
    depth = 0  # >0 while inside a tag we never mark in

    def replace(match):
        kind = match.lastgroup
        text = match.group(kind)
        slug = lookup.get((kind, text.lower() if kind == 'en' else text))
        if not slug or slug in used or len(used) >= max_marks:
            return match.group(0)
        used.append(slug)
        url = reverse('library:glossary_detail', args=[slug])
        return f'<a href="{url}" class="glossary-term" data-glossary="{html_lib.escape(slug)}">{text}</a>'

    out = []
    for piece in _TAG.split(html):
        if piece.startswith('<'):
            name_match = _TAG_NAME.match(piece)
            if name_match and name_match.group(2).lower() in SKIP_TAGS and not piece.rstrip().endswith('/>'):
                depth += -1 if name_match.group(1) else 1
                depth = max(depth, 0)
            out.append(piece)
        elif depth == 0 and piece.strip() and len(used) < max_marks:
            out.append(regex.sub(replace, piece))
        else:
            out.append(piece)
    return ''.join(out), used


def definitions_for(slugs, language_code):
    """{slug: {name, definition, url}} for the popovers, in the reader's language."""
    if not slugs:
        return {}
    from .models import GlossaryTerm

    terms = GlossaryTerm.objects.filter(slug__in=slugs, is_published=True)
    return {
        term.slug: {'name': term.display_name, 'definition': term.definition_for(language_code),
                    'url': term.get_absolute_url()}
        for term in terms
    }
