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
