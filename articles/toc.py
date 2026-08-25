import re
from html import unescape

from django.utils.text import slugify

# <h2>/<h3> only — matches what the seed content and CKEditor's 'articles'
# toolbar actually produce (heading, |, bold, italic...); a level-4+ heading
# would be unusual for a news/case-report article body.
HEADING_RE = re.compile(r'<(h[23])\b([^>]*)>(.*?)</\1>', re.IGNORECASE | re.DOTALL)
TAG_STRIP_RE = re.compile(r'<[^>]+>')
EXISTING_ID_RE = re.compile(r'\bid=["\']([^"\']+)["\']', re.IGNORECASE)

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
            base = slugify(text) or 'section'
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
