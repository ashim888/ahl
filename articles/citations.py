import re

# An editor types a plain [1], [2] placeholder wherever a citation belongs
# instead of hand-writing <sup><a href="#ref-1">1</a></sup> markup. The
# references list (article_detail.html) already auto-generates matching
# id="ref-N" anchors from the plain-text references field, one per line —
# this is the other half of that pairing.
CITATION_PATTERN = re.compile(r'\[(\d+)\]')


def linkify_citations(html_content):
    """Render-time transform of [N] placeholders into hyperlinked, superscript
    citation markers. Applied at render time (not on save) so the stored
    html_content stays exactly as the editor typed it in CKEditor — plain
    [N] placeholders, not generated markup that would need to be kept in
    sync by hand.
    """
    if not html_content:
        return html_content
    return CITATION_PATTERN.sub(r'<sup><a href="#ref-\1">\1</a></sup>', html_content)
