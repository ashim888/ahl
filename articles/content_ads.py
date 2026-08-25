import re

# Splits Article.html_content into chunks at paragraph boundaries so
# article_detail.html can interleave in-article ads between them — a
# full-width break between two paragraphs, not text wrapping around a
# floated box. A short article gets none at all; a long one gets up to
# MAX_IN_ARTICLE_ADS, spaced out rather than clustered near the top.
PARAGRAPH_CLOSE_RE = re.compile(r'</p\s*>', re.IGNORECASE)

MIN_PARAGRAPHS_BEFORE_FIRST_AD = 4
PARAGRAPHS_BETWEEN_ADS = 5
MAX_IN_ARTICLE_ADS = 3

# Alternates so a long article isn't broken up by the same shape over and
# over — see ads/models.py Zone.ARTICLE_IN_CONTENT / ARTICLE_CONTENT_BANNER.
IN_ARTICLE_AD_ZONES = ['article_in_content', 'article_content_banner']


def build_content_blocks(html_content):
    """Returns a list of (html_chunk, ad_zone) pairs for article_detail.html
    to render in order — `{{ html_chunk|safe }}` followed by
    `{% ad_slot ad_zone %}` when ad_zone isn't None (always None for the
    last block, since nothing goes after the final chunk of the article).
    A short article (too few paragraphs) is a single block with no ad zone.
    """
    if not html_content:
        return [(html_content, None)]

    paragraph_end_positions = [m.end() for m in PARAGRAPH_CLOSE_RE.finditer(html_content)]
    total_paragraphs = len(paragraph_end_positions)
    if total_paragraphs < MIN_PARAGRAPHS_BEFORE_FIRST_AD:
        return [(html_content, None)]

    injection_paragraph_indices = []
    next_at = MIN_PARAGRAPHS_BEFORE_FIRST_AD
    while next_at <= total_paragraphs and len(injection_paragraph_indices) < MAX_IN_ARTICLE_ADS:
        injection_paragraph_indices.append(next_at)
        next_at += PARAGRAPHS_BETWEEN_ADS

    blocks = []
    chunk_start = 0
    for i, paragraph_index in enumerate(injection_paragraph_indices):
        split_at = paragraph_end_positions[paragraph_index - 1]
        zone = IN_ARTICLE_AD_ZONES[i % len(IN_ARTICLE_AD_ZONES)]
        blocks.append((html_content[chunk_start:split_at], zone))
        chunk_start = split_at
    blocks.append((html_content[chunk_start:], None))
    return blocks
