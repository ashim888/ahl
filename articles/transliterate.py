"""Devanagari → Latin letters for URL slugs (स्वास्थ्य → swasthya).

Django's slugify drops every Devanagari letter, so a Nepali headline used
to get the slug "article-3f2a4". Article.save() now romanizes first. The
same rules, line for line, are in static/js/slug_quality.js (the editor's
slug checker and the Chrome extension), so the slug the checker suggests is
the slug the server would make — tests keep them in step.

Simple, readable romanization (not academic IAST): no diacritics, the
inherent "a" dropped at the end of a word (समाधान → samadhan) except after
a conjunct (राष्ट्र → rashtra) or in one-letter words (र → ra).
"""
import re

CONSONANTS = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng', 'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'n',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n', 'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm', 'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'w', 'श': 'sh',
    'ष': 'sh', 'स': 's', 'ह': 'h', 'क्ष': 'ksh', 'ज्ञ': 'gy', 'ड़': 'r', 'ढ़': 'rh', 'फ़': 'f', 'ज़': 'z',
}
VOWELS = {
    'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'i', 'उ': 'u', 'ऊ': 'u', 'ऋ': 'ri', 'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au',
    'ऍ': 'e', 'ऑ': 'o',
}
SIGNS = {
    'ा': 'a', 'ि': 'i', 'ी': 'i', 'ु': 'u', 'ू': 'u', 'ृ': 'ri', 'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au',
    'ॅ': 'e', 'ॉ': 'o',
}
MARKS = {'ं': 'n', 'ँ': 'n', 'ः': 'h', '़': '', 'ऽ': ''}
DIGITS = '०१२३४५६७८९'
VIRAMA = '्'
NUKTA = '़'
_DEVANAGARI = re.compile('[ऀ-ॿ]')


def _is_word_end(chars: list[str], j: int) -> bool:
    if j >= len(chars):
        return True
    c = chars[j]
    if MARKS.get(c):
        return False
    return not _DEVANAGARI.match(c)


def romanize(text: str) -> str:
    out = ''
    chars = list(text or '')
    word_start = 0
    after_virama = False
    i = 0
    while i < len(chars):
        ch = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ''
        triple = ch + nxt + (chars[i + 2] if i + 2 < len(chars) else '')
        if nxt == VIRAMA and triple in CONSONANTS:
            ch, i = triple, i + 2
        elif nxt == NUKTA and ch + NUKTA in CONSONANTS:
            ch, i = ch + NUKTA, i + 1
        if ch in CONSONANTS:
            latin = CONSONANTS[ch]
            out += latin
            nxt = chars[i + 1] if i + 1 < len(chars) else ''
            if nxt == VIRAMA:
                i += 2
                after_virama = True
                continue
            if nxt in SIGNS:
                out += SIGNS[nxt]
                i += 1
            elif not _is_word_end(chars, i + 1):
                out += 'a'
            elif after_virama or not re.search('[aeiou]', out[word_start:len(out) - len(latin)]):
                out += 'a'
            after_virama = False
            i += 1
            continue
        after_virama = False
        if ch in VOWELS:
            out += VOWELS[ch]
        elif ch in MARKS:
            out += MARKS[ch]
        elif ch in DIGITS:
            out += str(DIGITS.index(ch))
        elif ch in '।॥':
            out += ' '
        else:
            out += ch
        if not _DEVANAGARI.match(ch):
            word_start = len(out)
        i += 1
    return re.sub(r'aa(?=[^aeiou]|$)', 'a', out)
