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
from bleach.css_sanitizer import CSSSanitizer

_TRUSTED_SCRIPT_SRC_PREFIXES = (
    'https://d3js.org/',
)

# Video/audio embeds from the editor's "Insert media" button (mediaEmbed with
# previewsInData, see CKEDITOR_5_CONFIGS) — an <iframe> is kept only when it
# points at one of these players.
_TRUSTED_IFRAME_SRC_PREFIXES = (
    'https://www.youtube.com/embed/',
    'https://www.youtube-nocookie.com/embed/',
    'https://player.vimeo.com/video/',
    'https://www.dailymotion.com/embed/',
    'https://open.spotify.com/embed/',
)

_ALLOWED_TAGS = [
    'p', 'br', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'strong', 'b', 'em', 'i', 'u', 's', 'del', 'sup', 'sub',
    'a', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
    'span', 'div', 'img', 'figure', 'figcaption', 'iframe',
    'table', 'caption', 'colgroup', 'col', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th',
    'script',
]

# Inline styles the editor writes: alignment (text-align, incl. justify),
# image width after resizing, list numbering style, table borders/colours.
# Nothing that can position or overlay content (no position/top/left/z-index).
_CSS_SANITIZER = CSSSanitizer(allowed_css_properties=[
    'text-align', 'width', 'height', 'max-width', 'float', 'margin-left', 'margin-right',
    'list-style-type', 'vertical-align',
    'border', 'border-color', 'border-style', 'border-width', 'background-color', 'padding',
])


def _script_attribute_allowed(tag, name, value):
    if name == 'type':
        return True
    if name == 'src':
        return value.startswith(_TRUSTED_SCRIPT_SRC_PREFIXES)
    return False


def _iframe_attribute_allowed(tag, name, value):
    if name == 'src':
        return value.startswith(_TRUSTED_IFRAME_SRC_PREFIXES)
    # YouTube refuses to play ("Error 153") without knowing the embedding
    # site, which the site-wide Referrer-Policy (same-origin) withholds;
    # CKEditor adds this per-iframe override, and only this value is kept.
    if name == 'referrerpolicy':
        return value == 'strict-origin-when-cross-origin'
    return name in ('allow', 'allowfullscreen', 'frameborder', 'title', 'loading', 'style')


_BLOCK_WITH_STYLE = ['style']  # text-align from the Alignment button

_ALLOWED_ATTRIBUTES = {
    'a': ['href', 'id', 'name', 'target', 'rel'],
    'img': ['src', 'alt', 'width', 'height', 'class', 'style', 'loading'],
    'figure': ['class', 'style'],  # image / image-style-* / image_resized / media / table
    'div': ['id', 'class', 'data-oembed-url'],
    'span': ['id', 'class'],
    'p': _BLOCK_WITH_STYLE,
    'li': _BLOCK_WITH_STYLE,
    'blockquote': _BLOCK_WITH_STYLE,
    'h1': ['id', 'style'], 'h2': ['id', 'style'], 'h3': ['id', 'style'],
    'h4': ['id', 'style'], 'h5': ['id', 'style'], 'h6': ['id', 'style'],
    'ul': ['style'],
    'ol': ['style', 'start', 'reversed'],
    'code': ['class'],  # codeBlock's language-* class (see CKEDITOR_5_CONFIGS)
    'pre': ['class'],
    'table': ['style'],
    'col': ['style', 'span'],
    'td': ['colspan', 'rowspan', 'style'],
    'th': ['colspan', 'rowspan', 'style', 'scope'],
    'iframe': _iframe_attribute_allowed,
    'script': _script_attribute_allowed,
}

_ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


def sanitize_editorial_html(html):
    if not html:
        return html
    return bleach.clean(
        html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS, strip=True, css_sanitizer=_CSS_SANITIZER,
    )
