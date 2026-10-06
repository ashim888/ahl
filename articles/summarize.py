"""One- and two-line summary suggestions for an article's standfirst
(Article.abstract — shown under the headline and on cards).

Built in, no AI and no outside service: the suggestions are the article's own
strongest sentences, so they can't invent facts. Each sentence is scored on:

- position — news puts the most important fact first;
- overlap with the headline and the article's topics;
- concrete detail — numbers, percentages, money, dates ("impactful lines");
- a direct quote (a little: strong, but often needs context);
- length — 12–35 words reads as a standfirst; very short or long ones lose;
- standing alone — a sentence opening with "He", "This", "However"… needs the
  one before it, so it's marked down.

suggest() returns up to three different options: the best single sentence,
the best two sentences in a row (≤ MAX_CHARS), and the strongest sentence
with a number in it. English and Nepali (sentences end in "।").
"""
import html as html_lib
import re

from django.utils.html import strip_tags

MAX_CHARS = 280
IDEAL_MIN_CHARS = 90
IDEAL_MAX_CHARS = 220

# Where a sentence may end: "।", "!" or "?" before a space; "." only before
# a capital letter, digit or opening quote — so Nepali abbreviations
# ("५ से.मी. लामो") don't cut a sentence, and English ones ("Dr. Rai") are
# caught by _ABBREVIATION in sentences().
_SENTENCE_END = re.compile(
    r'[!?।]["”’)\]]*\s+'
    r'|\.["”’)\]]*\s+(?=["“‘(\[]?[A-Z0-9])'
    r'|(?<=[a-zA-Z0-9]\.)\s+(?=[ऀ-ॿ])'  # an English sentence followed by a Nepali one
)
_ABBREVIATION = re.compile(r'(?:\b(?:Mr|Mrs|Ms|Dr|Prof|St|No|vs|etc|Rs|approx|Govt|Dept|Fig)|\b[A-Z]|e\.g|i\.e)\.["”’)\]]*\s*$')
_WORD = re.compile(r'[\wऀ-ॿ]+')
_NUMBER = re.compile(r'(\d|[०-९])')
_STRONG_NUMBER = re.compile(r'(\d[\d,.]*\s?(%|percent|per cent|प्रतिशत|लाख|करोड|million|billion|crore|lakh))|(Rs\.?\s?\d|रु\.?\s?[०-९\d])', re.I)
_QUOTE = re.compile(r'["“].{12,}["”]')
_NEEDS_CONTEXT = {
    'he', 'she', 'it', 'they', 'this', 'that', 'these', 'those', 'however', 'but', 'also', 'and', 'so',
    'meanwhile', 'moreover', 'furthermore', 'still', 'yet', 'then', 'there', 'such', 'his', 'her', 'their', 'its',
    'उनी', 'उनले', 'यो', 'त्यो', 'तर', 'यस', 'उक्त', 'त्यसैले',
}
_STOPWORDS = {
    'the', 'a', 'an', 'of', 'in', 'on', 'for', 'to', 'and', 'or', 'is', 'are', 'was', 'were', 'be', 'with', 'by',
    'at', 'as', 'from', 'that', 'this', 'it', 'its', 'has', 'have', 'had', 'will', 'new', 'how', 'why', 'what',
    'र', 'को', 'का', 'की', 'मा', 'ले', 'लाई', 'छ', 'छन्', 'हो', 'पनि', 'गर्न', 'भएको',
}


def body_text(html: str) -> str:
    """Article HTML → plain text, one paragraph per line; drops figure
    captions, tables and code, which make poor standfirsts."""
    html = re.sub(r'<(figcaption|table|pre|code|script|style)\b.*?</\1>', ' ', html or '', flags=re.S | re.I)
    html = re.sub(r'</(p|h[1-6]|li|blockquote|div)>|<br\s*/?>', '\n', html, flags=re.I)
    text = html_lib.unescape(strip_tags(html))
    return '\n'.join(' '.join(line.split()) for line in text.splitlines() if line.strip())


def sentences(text: str) -> list[str]:
    """Plain text → sentences (English and Nepali), abbreviations kept whole."""
    out = []
    for paragraph in text.splitlines():
        start = 0
        for match in _SENTENCE_END.finditer(paragraph):
            candidate = paragraph[start:match.end()]
            if _ABBREVIATION.search(candidate):
                continue  # "Dr. Rai…" — keep going
            out.append(candidate.strip())
            start = match.end()
        if paragraph[start:].strip():
            out.append(paragraph[start:].strip())
    return [s for s in out if s]


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _score(sentence: str, index: int, focus: set[str]) -> float:
    words = _words(sentence)
    if len(words) < 6 or not sentence[-1:] in '.!?।"”\'’':
        return -1.0  # fragments, headings, list items
    score = 3.0 / (1 + index * 0.6)                       # the lead matters most
    content = {w for w in words if w not in _STOPWORDS}
    if focus:
        score += 2.5 * len(content & focus) / len(focus)  # about what the headline is about
    if _STRONG_NUMBER.search(sentence):
        score += 1.5
    elif _NUMBER.search(sentence):
        score += 0.8
    if _QUOTE.search(sentence):
        score += 0.4
    n = len(words)
    if 12 <= n <= 35:
        score += 1.0
    elif n > 45:
        score -= 1.5
    if words[0] in _NEEDS_CONTEXT:
        score -= 1.5
    if len(sentence) > MAX_CHARS:
        score -= 3.0
    elif len(sentence) > IDEAL_MAX_CHARS:
        score -= 1.0
    elif len(sentence) < IDEAL_MIN_CHARS * 2 // 3:
        score -= 1.0
    return score


def _clip(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS - 1].rsplit(' ', 1)[0].rstrip(',;:—-')
    return f'{cut}…'


def suggest(title: str, html: str, keywords: list[str] | None = None, limit: int = 3) -> list[dict]:
    """Up to `limit` distinct suggestions: [{'text', 'kind', 'chars'}]."""
    candidates = sentences(body_text(html))[:40]
    if not candidates:
        return []
    focus = {w for w in _words(' '.join([title or ''] + list(keywords or []))) if w not in _STOPWORDS}
    scored = [(_score(s, i, focus), i, s) for i, s in enumerate(candidates)]
    usable = [item for item in scored if item[0] > 0]
    if not usable:
        return []

    picks: list[tuple[str, str]] = []
    best = max(usable)
    picks.append(('lead', best[2]))

    pairs = []
    for (score_a, _i, a), (score_b, _j, b) in zip(scored, scored[1:]):
        # The second sentence may lean on the first ("He said…") — fine in a pair.
        if score_a > 0 and score_b > -1 and len(a) + len(b) + 1 <= MAX_CHARS:
            pairs.append((score_a + max(score_b, 0.5) * 0.7, f'{a} {b}'))
    if pairs:
        picks.append(('two_lines', max(pairs)[1]))

    numbered = [item for item in usable if _NUMBER.search(item[2])]
    if numbered:
        picks.append(('key_fact', max(numbered)[2]))

    for item in sorted(usable, reverse=True):
        picks.append(('alternative', item[2]))

    seen, out = set(), []
    for kind, text in picks:
        text = _clip(text)
        key = text.lower()
        if key in seen or any(key in other or other in key for other in seen):
            continue
        seen.add(key)
        out.append({'text': text, 'kind': kind, 'chars': len(text)})
        if len(out) == limit:
            break
    return out
