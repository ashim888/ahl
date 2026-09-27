from django import template

register = template.Library()


@register.filter
def split_comma(value):
    """Split a comma-separated string into a list of trimmed, non-empty parts —
    used to render Article.keywords (a flat CharField) as individual tag pills.
    """
    if not value:
        return []
    return [part.strip() for part in value.split(',') if part.strip()]


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
