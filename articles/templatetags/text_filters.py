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
def subject_initial(title):
    """Capital initial of a course title's second word — "Research Writing
    Fundamentals" → "W" — for its press plate. Course titles tend to open
    with the same field word ("Research …"), so first letters would repeat
    across the catalog; the second word is usually the subject.
    """
    words = str(title or '').split()
    return (words[1] if len(words) > 1 else ''.join(words))[:1].upper()


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
