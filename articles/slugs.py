"""Article slugs made on the server — the same slug the editor's slug
checker suggests (static/js/slug_quality.js `suggest()`, ported line for
line; tests keep the two in step).

A slug is the headline's meaningful words: romanized when Nepali
(articles/transliterate.py), lowercase a–z/0–9 joined by hyphens, filler
words ("the", "of", "ra", "ko"…) dropped, at most 6 words and 60 characters.
No random code on the end: the article's short_code already gives it a
second address (/articles/<code>/ redirects to the slug — see
articles.views.article_short_link). Only a clash adds "-2", "-3"…
"""
import re
import unicodedata

from .transliterate import romanize

STOPWORDS = set((
    'a an the and or but nor of in on at to for from by with as is are was were be been being it its '
    'this that these those into about over after before than then so if not no yes can will just how why what '
    'when where who which do does did has have had your our their his her you we they i me my '
    'ra ko ka ki ma le lai chha chhan ho pani tatha wa evam'
).split())
MAX_GOOD = 60
MAX_WORDS = 6


def words(text: str) -> list[str]:
    folded = unicodedata.normalize('NFKD', romanize(str(text or '')).lower())
    folded = ''.join(ch for ch in folded if not unicodedata.combining(ch)).replace("'", '').replace('’', '')
    return [w for w in re.split(r'[^a-z0-9]+', folded) if w]


def suggest_slug(title: str, keywords=()) -> str:
    picked: list[str] = []
    for word in words(title):
        if word in STOPWORDS or word in picked or len(picked) >= MAX_WORDS:
            continue
        if len('-'.join(picked) + '-' + word) <= MAX_GOOD:
            picked.append(word)
    focus = next((f for f in ('-'.join(words(k)) for k in keywords) if f), '')
    if focus and focus not in '-'.join(picked) and len(focus + '-' + '-'.join(picked)) <= MAX_GOOD:
        focus_words = focus.split('-')
        picked = (focus_words + [w for w in picked if w not in focus_words])[:MAX_WORDS]
    return '-'.join(picked)


def alt_from_slug(slug: str) -> str:
    """The featured image's default description: the slug's words, e.g.
    "dengue-cases-rise-kathmandu" → "Dengue cases rise kathmandu" (a clash
    number like "-2" is dropped). Editors can replace it with a description
    of the picture itself. Mirrored by altFromSlug() in article_form.html."""
    words = [w for w in (slug or '').split('-') if w]
    if len(words) > 1 and words[-1].isdigit() and len(words[-1]) < 3:
        words = words[:-1]
    text = ' '.join(words)
    return (text[:1].upper() + text[1:])[:250]


def unique_article_slug(base: str, *, exclude_pk=None) -> str:
    """`base`, or base-2, base-3… — never another article's slug, nor
    another article's short code (/articles/<code>/ is its short link)."""
    from .models import Article

    others = Article.objects.exclude(pk=exclude_pk) if exclude_pk else Article.objects.all()
    candidate, n = base, 2
    while others.filter(slug=candidate).exists() or others.filter(short_code=candidate).exists():
        candidate, n = f'{base}-{n}', n + 1
    return candidate
