import re

# An editor types a plain [1], [2] placeholder wherever a citation belongs
# instead of hand-writing <sup><a href="#ref-1">1</a></sup> markup. The
# references list (article_detail.html) already auto-generates matching
# id="ref-N" anchors from the plain-text references field, one per line —
# this is the other half of that pairing.
CITATION_PATTERN = re.compile(r'\[(\d+)\]')

# CKEditor's codeBlock/inline-code output (<pre><code>...</code></pre> or a
# bare <code>...</code>) — never linkify inside these. Bracket-index syntax
# like arr[1] or data[0] is everyday code, not a citation, in most of the
# languages the codeBlock toolbar offers (see CKEDITOR_5_CONFIGS in
# settings.py); matching it there would corrupt the code sample itself.
CODE_BLOCK_PATTERN = re.compile(r'<pre\b.*?</pre>|<code\b.*?</code>', re.IGNORECASE | re.DOTALL)


def linkify_citations(html_content):
    """Render-time transform of [N] placeholders into hyperlinked, superscript
    citation markers. Applied at render time (not on save) so the stored
    html_content stays exactly as the editor typed it in CKEditor — plain
    [N] placeholders, not generated markup that would need to be kept in
    sync by hand. Skips the contents of any code block/inline code entirely.
    """
    if not html_content:
        return html_content

    pieces = CODE_BLOCK_PATTERN.split(html_content)
    code_blocks = CODE_BLOCK_PATTERN.findall(html_content)
    linkified = (CITATION_PATTERN.sub(r'<sup><a href="#ref-\1">\1</a></sup>', piece) for piece in pieces)
    # re.split() on a pattern with no capture groups drops the matched code
    # blocks from `pieces` — re-interleave them back in, untouched, between
    # the linkified non-code pieces on either side of each one.
    result = [next(linkified)]
    for code_block in code_blocks:
        result.append(code_block)
        result.append(next(linkified))
    return ''.join(result)


def uncited_references_warning(article) -> str:
    """The editor's after-save warning when an article lists references but
    its text never cites one with [1], [2]… — the reference list then reads
    as decoration, and a reader can't tell which claim rests on which
    source. Empty when there's nothing to warn about. Code samples don't
    count as citations (same rule as linkify_citations)."""
    count = article.reference_count
    if not count:
        return ''
    text = CODE_BLOCK_PATTERN.sub('', article.html_content or '')
    if CITATION_PATTERN.search(text):
        return ''
    sources = f'{count} source{"s" if count > 1 else ""}'
    return (
        f'"{article.title}" lists {sources} but the text doesn\'t cite any. '
        'Type [1], [2]… after each claim that comes from a source, so readers can check it.'
    )
