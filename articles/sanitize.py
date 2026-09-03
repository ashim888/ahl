"""Sanitizes editor-authored HTML before it's stored — Article.html_content
and NewsletterIssue.body_html are documented as "trusted, editor-authored
HTML" and rendered unescaped (`|safe`), on the basis that only EDITORIAL_ROLES
accounts can write to them. That's still the primary control here; this is
defense in depth for the case that trust boundary fails (a compromised or
malicious editor account) — run once at save time (ArticleForm/
NewsletterIssueForm clean_*, not on every render), so the stored value is
safe for every consumer of these fields (web render, RSS/Atom feed, the
newsletter send task) without each one having to remember to sanitize.

`<script>` stays on the allowed list — deliberately, not an oversight. CKEditor's
'articles' config ships a sourceEditing button specifically so an editor can
drop into raw HTML to embed a D3.js chart (see CKEDITOR_5_CONFIGS in
settings.py / ROADMAP.md's WYSIWYG section) — a standard allowlist without
<script> would silently break that shipped feature. `src` is restricted to
the one CDN this project actually preloads (article_detail.html only loads
d3js.org when html_content is present); an inline <script> with no `src` is
always allowed, since that's D3's actual usage pattern (load the library
once via that preloaded <script src>, then use it inline). This is a
materially weaker guarantee than a normal sanitizer — script is exactly the
tag XSS relies on — accepted here as the explicit tradeoff for keeping the
chart-embed feature working, not a blind spot.
"""
import bleach

_TRUSTED_SCRIPT_SRC_PREFIXES = (
    'https://d3js.org/',
)

_ALLOWED_TAGS = [
    'p', 'br', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'strong', 'b', 'em', 'i', 'u', 'sup', 'sub',
    'a', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
    'span', 'div', 'img',
    'table', 'thead', 'tbody', 'tr', 'td', 'th',
    'script',
]


def _script_attribute_allowed(tag, name, value):
    if name == 'type':
        return True
    if name == 'src':
        return value.startswith(_TRUSTED_SCRIPT_SRC_PREFIXES)
    return False


_ALLOWED_ATTRIBUTES = {
    'a': ['href', 'id', 'name', 'target', 'rel'],
    'img': ['src', 'alt', 'width', 'height'],
    # No `style` — bleach only sanitizes it with an optional css_sanitizer
    # dependency this project doesn't have installed; D3 sets element style
    # via JS at runtime on containers it creates, not through a static
    # inline style= attribute the editor would type, so there's nothing
    # real lost by leaving it off the allowlist.
    'div': ['id', 'class'],
    'span': ['id', 'class'],
    'h1': ['id'], 'h2': ['id'], 'h3': ['id'], 'h4': ['id'], 'h5': ['id'], 'h6': ['id'],
    'code': ['class'],  # codeBlock's language-* class (see CKEDITOR_5_CONFIGS)
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
    'script': _script_attribute_allowed,
}

_ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


def sanitize_editorial_html(html):
    if not html:
        return html
    return bleach.clean(
        html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS, strip=True,
    )
