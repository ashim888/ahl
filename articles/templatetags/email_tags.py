"""Branding/URL helpers for email templates (templates/email/base.html and
everything that extends it).

Emails are rendered from places with no request and no context processors:
django_comments_xtd's own send functions, the newsletter's background
worker, model signals. So instead of relying on the journal_settings
context processor, templates load these tags and read settings directly —
the same layout then works identically from every call site.
"""
from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


def _site_url() -> str:
    return settings.SITE_BASE_URL.rstrip('/')


@register.simple_tag
def email_branding() -> dict:
    """Journal name/tagline/publisher/contact + absolute site and logo URLs."""
    logo = static('images/logo.png')
    return {
        'name': settings.JOURNAL_NAME,
        'tagline': settings.JOURNAL_TAGLINE,
        'publisher': getattr(settings, 'JOURNAL_PUBLISHER', ''),
        'contact_email': getattr(settings, 'JOURNAL_CONTACT_EMAIL', ''),
        'site_url': _site_url(),
        'logo_url': logo if logo.startswith('http') else f'{_site_url()}{logo}',
    }


@register.filter
def absolute_url(path) -> str:
    """Turns a site-relative path ("/articles/x/") into a full URL using
    SITE_BASE_URL; already-absolute URLs pass through unchanged.
    """
    path = str(path or '')
    if path.startswith(('http://', 'https://', 'mailto:')):
        return path
    return f'{_site_url()}/{path.lstrip("/")}'


@register.filter
def append(value, suffix) -> str:
    """String concatenation that, unlike Django's `add`, never fails on
    mixed types — e.g. building "<article url>#c<comment pk>" in a template.
    """
    return f'{value if value is not None else ""}{suffix if suffix is not None else ""}'
