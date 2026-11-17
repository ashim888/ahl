"""Google Form surveys embedded in a story (Article.survey_url).

Editors paste the form's share link (docs.google.com/forms/d/e/<id>/viewform)
and the page embeds it (?embedded=true). Answers go straight into the
editor's Google account, so the site stores nothing. The short forms.gle
link can't be embedded without fetching it, so it's refused with a hint.
"""
import re
from urllib.parse import urlparse

from django.core.exceptions import ValidationError

_PATH = re.compile(r'^/forms/d/(e/)?([A-Za-z0-9_-]{10,})(?:/|$)')


def google_form_embed_url(url: str) -> str:
    """The embeddable address of a Google Form link, or '' if it isn't one."""
    if not url:
        return ''
    parsed = urlparse(url.strip())
    if (parsed.hostname or '').lower() != 'docs.google.com':
        return ''
    match = _PATH.match(parsed.path)
    if not match:
        return ''
    return f'https://docs.google.com/forms/d/{match[1] or ""}{match[2]}/viewform?embedded=true'


def validate_google_form_url(url: str):
    host = (urlparse((url or '').strip()).hostname or '').lower()
    if host == 'forms.gle':
        raise ValidationError('Short forms.gle links can\'t be embedded. Open the link, then copy the full '
                              'address from the browser (it starts with docs.google.com/forms/).')
    if not google_form_embed_url(url):
        raise ValidationError('Paste a Google Form link: the address starts with docs.google.com/forms/.')
