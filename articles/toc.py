import re
from html import unescape

from django.utils.text import slugify

# <h2>/<h3> only — matches what the seed content and CKEditor's 'articles'
# toolbar actually produce (heading, |, bold, italic...); a level-4+ heading
# would be unusual for a news/case-report article body.
HEADING_RE = re.compile(r'<(h[23])\b([^>]*)>(.*?)</\1>', re.IGNORECASE | re.DOTALL)
TAG_STRIP_RE = re.compile(r'<[^>]+>')
EXISTING_ID_RE = re.compile(r'\bid=["\']([^"\']+)["\']', re.IGNORECASE)

# A whole paragraph in bold — how a section title arrives when text is
# pasted from Word or Google Docs, or typed with Bold instead of the
# Heading menu: <p ...><strong>Title</strong></p> (also <b>, &nbsp;s, an
# <em> inside). See promote_bold_headings.
BOLD_PARAGRAPH_RE = re.compile(
    r'<p\b[^>]*>(?:\s|&nbsp;)*<(strong|b)\b[^>]*>(?P<inner>(?:(?!</?(?:p|strong|b)\b).)*?)</\1>'
    r'(?:\s|&nbsp;|<br\s*/?>)*</p>',
    re.IGNORECASE | re.DOTALL,
)
# "२.१ …", "2.1 …" — a numbered sub-section.
SUBSECTION_RE = re.compile(r'^[0-9०-९]+\.[0-9०-९]+')
BOLD_HEADING_MAX_CHARS = 150
CONTAINER_RE = re.compile(r'<(/?)(blockquote|table|li|figure)\b', re.IGNORECASE)

DEVANAGARI_RE = re.compile(r'[\u0900-\u097F]')


def heading_slug(text: str) -> str:
    """Anchor id for a heading: Django's slugify for English (unchanged, so
    existing links keep working); for Nepali, keyword_slug, which keeps the
    vowel signs slugify would drop ('के हो?' → 'के-हो')."""
    if DEVANAGARI_RE.search(text):
        from .models import keyword_slug

        return keyword_slug(text)
    return slugify(text)


# Below this many headings, a sidebar nav has nothing useful to jump
# between — article_detail.html only renders the "In This Article" block
# once extract_toc's second return value has more than this many entries.
MIN_HEADINGS_FOR_TOC = 1


def extract_toc(html_content):
    """Gives every <h2>/<h3> in html_content a stable id (adding one, from
    its text, if it doesn't already have one) and returns
    (html_with_ids, toc_entries) — toc_entries is an ordered list of
    {'level': 2|3, 'text': ..., 'id': ...} for the sticky "In This Article"
    sidebar nav (article_detail.html) to link against with `#id` anchors and
    highlight via IntersectionObserver as the reader scrolls past each one.

    Run this once, at render time, same place as citations.linkify_citations
    and content_ads.build_content_blocks — the stored html_content itself
    stays exactly as CKEditor produced it, headings included.
    """
    if not html_content:
        return html_content, []

    html_content = promote_bold_headings(html_content)
    toc_entries = []
    used_ids = set()

    def add_id(match):
        tag, attrs, inner_html = match.group(1), match.group(2), match.group(3)
        text = unescape(TAG_STRIP_RE.sub('', inner_html)).strip()
        if not text:
            return match.group(0)

        existing = EXISTING_ID_RE.search(attrs)
        if existing:
            heading_id = existing.group(1)
        else:
            base = heading_slug(text) or 'section'
            heading_id = base
            suffix = 2
            while heading_id in used_ids:
                heading_id = f'{base}-{suffix}'
                suffix += 1
            attrs = f'{attrs} id="{heading_id}"'

        used_ids.add(heading_id)
        toc_entries.append({'level': int(tag[1]), 'text': text, 'id': heading_id})
        return f'<{tag}{attrs}>{inner_html}</{tag}>'

    html_with_ids = HEADING_RE.sub(add_id, html_content)
    return html_with_ids, toc_entries


def promote_bold_headings(html_content: str) -> str:
    """In an article with no real <h2>/<h3>, each paragraph that is all
    bold and heading-length becomes an <h2> (an <h3> when it's numbered
    like "2.1"), so it shows as a heading and fills "In This Article".
    Paragraphs inside a quote, table, list or figure are left alone, as is
    any article that already uses the Heading menu. Display only — the
    stored text isn't changed.
    """
    if HEADING_RE.search(html_content):
        return html_content

    def promote(match):
        depth = 0
        for tag in CONTAINER_RE.finditer(html_content, 0, match.start()):
            depth += -1 if tag.group(1) else 1
        if depth > 0:
            return match.group(0)
        inner = match.group('inner')
        text = unescape(TAG_STRIP_RE.sub('', inner)).replace('\xa0', ' ').strip()
        if not text or len(text) > BOLD_HEADING_MAX_CHARS:
            return match.group(0)
        level = 'h3' if SUBSECTION_RE.match(text) else 'h2'
        return f'<{level}>{inner.replace("&nbsp;", " ").strip()}</{level}>'

    return BOLD_PARAGRAPH_RE.sub(promote, html_content)
