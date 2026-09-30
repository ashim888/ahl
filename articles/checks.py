"""System checks for settings that fail silently at runtime.

SITE_BASE_URL builds every absolute link in outgoing email (comment
confirmation, newsletter confirm/unsubscribe, follow-up notifications) —
see articles/templatetags/email_tags.py and newsletter/emails.py. Left at its
localhost default on a production server, the site still works in the
browser but every emailed link is dead, and nothing errors anywhere.
"""
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, register

LOCAL_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', ''}


@register(Tags.security, deploy=True)
def check_site_base_url(app_configs, **kwargs):
    """Runs under `manage.py check --deploy` (deploy.sh step 7)."""
    if settings.DEBUG:
        return []
    parsed = urlparse(settings.SITE_BASE_URL)
    errors = []
    if (parsed.hostname or '') in LOCAL_HOSTS:
        errors.append(Error(
            f'SITE_BASE_URL is "{settings.SITE_BASE_URL}" with DEBUG off — every link in outgoing email will point there.',
            hint='Set SITE_BASE_URL=https://your-domain in the server .env, then restart the app and run migrate.',
            id='ajna.E001',
        ))
    elif parsed.scheme != 'https':
        errors.append(Error(
            f'SITE_BASE_URL "{settings.SITE_BASE_URL}" is not https.',
            hint='Emailed confirmation/unsubscribe links should use https://.',
            id='ajna.E002',
        ))
    return errors


@register(Tags.security, deploy=True)
def check_payment_gateway(app_configs, **kwargs):
    """PAYMENT_GATEWAY defaults to 'stub', which treats every payment as
    successful — on a live server that gives every paid subscription,
    article and course away free, silently. Opt out only on a staging
    server with ALLOW_STUB_PAYMENTS=True."""
    if settings.DEBUG or settings.PAYMENT_GATEWAY != 'stub' or getattr(settings, 'ALLOW_STUB_PAYMENTS', False):
        return []
    return [Error(
        'PAYMENT_GATEWAY is "stub" with DEBUG off — every checkout succeeds without payment.',
        hint='Set PAYMENT_GATEWAY=fonepay (and the FONEPAY_* values) in the server .env. '
             'On a staging server only, ALLOW_STUB_PAYMENTS=True silences this.',
        id='ajna.E003',
    )]


@register(Tags.security, deploy=True)
def check_debug_off(app_configs, **kwargs):
    """`check --deploy` only runs on a server (deploy.sh), and every other
    check here skips itself while DEBUG is on — so a server left in debug
    mode would pass them all while showing full error pages (code,
    settings) to the public. Staging can opt out with ALLOW_DEBUG_DEPLOY."""
    if not settings.DEBUG or getattr(settings, 'ALLOW_DEBUG_DEPLOY', False):
        return []
    return [Error(
        'DEBUG is on — this server would show full debug error pages to the public.',
        hint='Set DEBUG=False in the server .env (or remove the line).',
        id='ajna.E004',
    )]
