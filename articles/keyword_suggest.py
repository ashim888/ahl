"""Keyword suggestions for the article form, from the unsaved headline,
summary and text. Built in, like articles/summarize.py: no AI and no
outside service.

Two kinds of suggestion:

- existing — a Keyword the site already has whose name appears in the
  article. These come first: reusing a keyword keeps a topic page together
  instead of splitting it into near-duplicates (see the Keyword docstring).
- new — a phrase the article keeps coming back to (1–3 content words,
  repeated, or in the headline). One that folds to an existing keyword's slug
  is shown as that existing keyword instead.

Scoring: mentions in the text, plus a strong bonus for the headline and a
smaller one for the summary; multi-word phrases and capitalised names (in the
middle of a sentence) get a little more. Nepali works too: postpositions are
joined to the word ("काठमाडौंमा"), so existing Nepali keywords match as
substrings, and common endings are trimmed before counting new phrases.
"""
import math
import re
from collections import Counter

from django.db.models import Count

from .models import Keyword, keyword_slug
from .summarize import body_text, sentences

LIMIT = 8
_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9\'’-]*|[ऀ-ॿ]+')
_DEVANAGARI = re.compile(r'[ऀ-ॿ]')
_NEPALI_ENDINGS = ('हरूको', 'हरूले', 'हरूमा', 'हरू', 'लाई', 'बाट', 'को', 'का', 'की', 'मा', 'ले')
STOPWORDS = set((
    'a about above after again against all also am an and any are as at be because been before being below '
    'between both but by can could did do does doing down during each few for from further had has have having '
    'he her here hers him his how i if in into is it its itself just me more most my no nor not now of off on '
    'once only or other our ours out over own same she should so some such than that the their theirs them then '
    'there these they this those through to too under until up very was we were what when where which while who '
    'whom why will with would you your yours said says say according including include includes may might must '
    'one two three new many much like well even still yet however per cent percent year years week weeks day days '
    'month months time people last first get got make made use used using told added since around among within '
    'without across another every us mr mrs ms dr also often already several'
    # news words that are never what a story is "about"
    ' case rise increase decrease report number result study level rate part way thing lot need help issue '
    'problem show find found take give call plan work today yesterday tomorrow sunday monday tuesday wednesday '
    'thursday friday saturday official officials expert let lets'
    ' र को का की मा ले लाई छ छन् हो पनि गर्न भएको तथा वा एवं यो त्यो यस उक्त भने गरेको गरेका रहेको रहेका हुन्छ '
    'गर्ने थियो थिए उनी उनले सबै अनुसार लागि तर बारे हुने भन्ने गरी सक्ने'
).split())


def _norm(token: str) -> str:
    """Lowercase; fold English plurals and trim Nepali endings so
    "vaccines"/"vaccine" and "डेंगुको"/"डेंगु" count together."""
    token = token.lower().replace('’', "'")
    if _DEVANAGARI.search(token):
        for ending in _NEPALI_ENDINGS:
            if token.endswith(ending) and len(token) > len(ending) + 1:
                return token[:-len(ending)]
        return token
    token = token.removesuffix("'s")
    if len(token) > 3 and token.endswith('s') and not token.endswith(('ss', 'us', 'is')):
        token = token[:-1]
    return token


def _tokens(text: str) -> list[tuple[str, str]]:
    """[(normalised, original)]"""
    return [(_norm(t), t.strip("'’-")) for t in _TOKEN.findall(text or '')]


def _phrase_counts(text: str, n_max: int = 4) -> Counter:
    """How often each 1..n_max-word run of normalised tokens occurs."""
    counts = Counter()
    for sentence in sentences(text) or [text]:
        words = [n for n, _ in _tokens(sentence)]
        for n in range(1, n_max + 1):
            for i in range(len(words) - n + 1):
                counts[tuple(words[i:i + n])] += 1
    return counts


def _existing(title, summary, body, exclude_slugs):
    texts = {'title': title, 'summary': summary, 'body': body}
    counts = {k: _phrase_counts(v) for k, v in texts.items()}
    lowered = {k: v.lower() for k, v in texts.items()}
    found = []
    for keyword in Keyword.objects.annotate(uses=Count('articles')).only('name', 'slug'):
        if keyword.slug in exclude_slugs:
            continue
        if _DEVANAGARI.search(keyword.name):
            needle = keyword.name.lower()
            hits = {k: v.count(needle) for k, v in lowered.items()}
        else:
            key = tuple(n for n, _ in _tokens(keyword.name))
            if not key:
                continue
            if all(k in STOPWORDS for k in key):
                # "who" stored for WHO: only the capitalised acronym counts, not the pronoun
                acronym = re.compile(r'\b' + re.escape(keyword.name.upper()) + r'\b')
                hits = {k: len(acronym.findall(v)) for k, v in texts.items()}
            else:
                hits = {k: c.get(key, 0) for k, c in counts.items()}
        if not hits['title'] and hits['body'] + hits['summary'] < 2:
            continue  # a single passing mention isn't what the story is about
        score = hits['body'] + 2 * min(hits['summary'], 1) + 4 * min(hits['title'], 1) + 0.5 * math.log1p(keyword.uses)
        found.append((score, keyword, hits))
    return found


def _new_phrases(title, summary, body):
    """Content-word runs (no stopwords inside), with their most common casing."""
    counts, forms, capitalised, in_title = Counter(), {}, Counter(), set()
    for where, text in (('title', title), ('summary', summary), ('body', body)):
        for sentence in sentences(text) or [text]:
            tokens = _tokens(sentence)
            for n in (1, 2, 3):
                for i in range(len(tokens) - n + 1):
                    run = tokens[i:i + n]
                    keys = tuple(k for k, _ in run)
                    if any(k in STOPWORDS or len(k) < 3 or k.isdigit() for k in keys):
                        continue
                    if where == 'title':
                        in_title.add(keys)
                        continue
                    counts[keys] += 1
                    forms.setdefault(keys, Counter())[' '.join(o for _, o in run)] += 1
                    if i > 0 and all(o[:1].isupper() for _, o in run):
                        capitalised[keys] += 1
    candidates = []
    for keys, n in counts.items():
        # A headline phrase needs one more mention in the text; others must recur.
        if n < (1 if keys in in_title else 2 if len(keys) > 1 else 3):
            continue
        score = n * (1 + 0.6 * (len(keys) - 1)) + (4 if keys in in_title else 0)
        if capitalised[keys] >= max(1, n // 2):
            score += 1.5
        name = forms[keys].most_common(1)[0][0] if keys in forms else ' '.join(keys)
        if name.islower() and not _DEVANAGARI.search(name):
            name = name[:1].upper() + name[1:]
        candidates.append((score, keys, name, n, keys in in_title))
    candidates.sort(key=lambda c: (-c[0], -len(c[1])))
    # Drop a phrase that only ever appears inside a longer one ("Kathmandu" under "Kathmandu Valley").
    kept = []
    for candidate in candidates:
        # n is the mention count: the shorter one never appears on its own
        if any(_contains(other[1], candidate[1]) and other[3] >= candidate[3] for other in kept):
            continue
        kept.append(candidate)
    return kept


def _contains(longer, shorter):
    n = len(shorter)
    return len(longer) > n and any(longer[i:i + n] == shorter for i in range(len(longer) - n + 1))


def _why(hits_title, mentions):
    parts = ['in headline'] if hits_title else []
    if mentions:
        parts.append(f'{mentions} mention{"s" if mentions != 1 else ""}')
    return ' · '.join(parts)


def suggest_keywords(title: str, html: str, summary: str = '', current=(), limit: int = LIMIT) -> list[dict]:
    """Up to `limit` suggestions, existing keywords first:
    [{'value', 'existing', 'why'}]. Keywords already on the article
    (`current`, names) are left out."""
    title, summary, body = title or '', summary or '', body_text(html)
    if not (title.strip() or body.strip()):
        return []
    taken = {keyword_slug(name) for name in current if name.strip()}

    out, seen = [], set(taken)
    for _score, keyword, hits in sorted(_existing(title, summary, body, taken), key=lambda f: -f[0]):
        out.append({'value': keyword.name, 'existing': True, 'why': _why(hits['title'], hits['body'] + hits['summary'])})
        seen.add(keyword.slug)

    for _score, _keys, name, mentions, in_title in _new_phrases(title, summary, body):
        if len(out) >= limit:
            break
        slug = keyword_slug(name)
        if not slug or slug in seen:
            continue
        match = Keyword.objects.filter(slug=slug).first()  # e.g. "Vaccines" when "vaccine" exists
        out.append({'value': match.name if match else name, 'existing': bool(match), 'why': _why(in_title, mentions)})
        seen.add(slug)
    return out[:limit]
