import re

from django import template
from django.utils.html import urlize
from django.utils.safestring import mark_safe

register = template.Library()

# A bare DOI in a reference ("doi:10.1000/xyz123" or just "10.1000/xyz123"),
# not one already inside a doi.org URL. Trailing punctuation isn't part of it.
DOI_PATTERN = re.compile(r'(?<![/\w.])(?:doi:\s*)?(10\.\d{4,9}/[^\s<>"]*[^\s<>".,;:)\]])', re.IGNORECASE)
ANCHOR_PATTERN = re.compile(r'(<a\b[^>]*>.*?</a>)', re.IGNORECASE | re.DOTALL)


@register.filter
def image_alt(article):
    """{{ article|image_alt }} — the featured image's description, or empty
    when it's only the headline again (the default Article.save fills in):
    the picture then sits beside the headline as decoration, and a screen
    reader shouldn't read the headline twice."""
    alt = (article.featured_image_alt or '').strip()
    return '' if alt == (article.title or '').strip()[:250] else alt


@register.filter(needs_autoescape=True)
def reference_links(text, autoescape=True):
    """{{ reference|reference_links }} — |urlize, plus a link to doi.org for
    a bare DOI, so a reader can open the source behind a reference."""
    html = urlize(text, nofollow=True, autoescape=autoescape)
    parts = ANCHOR_PATTERN.split(html)  # odd items are links urlize already made
    for i in range(0, len(parts), 2):
        parts[i] = DOI_PATTERN.sub(
            lambda m: f'<a href="https://doi.org/{m.group(1)}" rel="nofollow">{m.group(0)}</a>', parts[i],
        )
    return mark_safe(''.join(parts))


@register.filter
def split_comma(value):
    """Split a comma-separated string into a list of trimmed, non-empty parts —
    used to render Article.keywords (a flat CharField) as individual tag pills.
    """
    if not value:
        return []
    return [part.strip() for part in value.split(',') if part.strip()]


def _first_glyph(text):
    """The first letter as a reader sees it: a base letter plus its vowel
    signs and marks, and in Devanagari any conjunct joined by a virama
    ("वि", "क्ष", "श्रु"), not just the first code point ("व")."""
    import unicodedata
    text = str(text or '').strip()
    if not text:
        return ''
    glyph = text[0]
    for ch in text[1:]:
        if unicodedata.category(ch).startswith('M') or glyph.endswith('\u094d'):
            glyph += ch
        else:
            break
    return glyph.upper()


@register.filter
def plate_initial(title):
    """{{ title|plate_initial }} — the press plate's big letter (see _first_glyph)."""
    return _first_glyph(title)


@register.filter
def subject_initial(title):
    """Capital initial of a course title's second word — "Research Writing
    Fundamentals" → "W" — for its press plate. Course titles tend to open
    with the same field word ("Research …"), so first letters would repeat
    across the catalog; the second word is usually the subject.
    """
    words = str(title or '').split()
    return _first_glyph(words[1] if len(words) > 1 else ''.join(words))


@register.filter
def content_lang(value, default='en'):
    """'ne' when `value` is mostly Devanagari script, else `default` — used
    as a lang="" attribute on an article so Nepali-script content gets the
    :lang(ne) typography rules in base.html even when the site UI itself is
    in English. "Mostly" = at least 30% of its letters, so an English piece
    quoting a Nepali phrase isn't flipped, but a Nepali piece with a few
    English terms is.
    """
    # isalpha() counts base letters only — Devanagari vowel signs and
    # viramas are combining marks, so one Nepali word isn't over-counted
    # against an English one.
    letters = [ch for ch in str(value or '') if ch.isalpha()]
    if not letters:
        return default
    devanagari = sum(1 for ch in letters if 'ऀ' <= ch <= 'ॿ')
    return 'ne' if devanagari / len(letters) >= 0.3 else default


@register.filter
def headline_parts(title):
    """A headline split for the homepage cover's two-tone treatment:
    {'main', 'accent', 'subtitle'} — a closing "(…)" becomes the coloured
    accent ("डिमेन्सिया (बिर्सने रोग)"), and the part after ": " or " — "
    the smaller second line ("The Human Brain: How It Works"). Anything
    else is all main."""
    title = (title or '').strip()
    parts = {'main': title, 'accent': '', 'subtitle': ''}
    opening = title.rfind('(')
    if title.endswith(')') and opening > 0:
        parts['main'], parts['accent'] = title[:opening].rstrip(), title[opening:]
        return parts
    for separator in (': ', ' — ', ' – '):
        main, found, rest = title.partition(separator)
        if found and main.strip() and rest.strip():
            parts['main'], parts['subtitle'] = main.strip(), rest.strip()
            return parts
    return parts
