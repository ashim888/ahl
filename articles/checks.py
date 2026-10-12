"""System checks for settings that fail silently at runtime.

SITE_BASE_URL builds every absolute link in outgoing email (comment
confirmation, newsletter confirm/unsubscribe, follow-up notifications) —
see articles/templatetags/email_tags.py and newsletter/emails.py. Left at its
localhost default on a production server, the site still works in the
browser but every emailed link is dead, and nothing errors anywhere.
"""
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

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


@register(Tags.security, deploy=True)
def check_receipt_details(app_configs, **kwargs):
    """Every paid checkout emails a receipt with the seller's details; with
    real payments switched on they should be filled in."""
    if settings.DEBUG or settings.PAYMENT_GATEWAY != 'fonepay':
        return []
    missing = [name for name in ('BUSINESS_PAN', 'BUSINESS_ADDRESS') if not getattr(settings, name, '')]
    if not missing:
        return []
    return [Warning(
        f'{", ".join(missing)} not set — receipts go out without the business\'s PAN/address.',
        hint='Set BUSINESS_LEGAL_NAME, BUSINESS_PAN and BUSINESS_ADDRESS in the server .env.',
        id='ajna.W001',
    )]


@register(Tags.security, deploy=True)
def check_backups(app_configs, **kwargs):
    """Nightly off-site backups (ajna_health_lens/backups.py) need both settings."""
    if settings.DEBUG or (settings.BACKUP_EMAIL and settings.BACKUP_ENCRYPTION_PASSWORD):
        return []
    return [Warning(
        'Emailed database backups are off — the only backups are on this server.',
        hint='Set BACKUP_EMAIL and BACKUP_ENCRYPTION_PASSWORD in the server .env (keep the password in a password manager too).',
        id='ajna.W002',
    )]


@register(Tags.security, deploy=True)
def check_admin_emails(app_configs, **kwargs):
    """Every alert (server errors, broken links, failed backups, a stopped
    worker) goes to ADMINS — with none set, they go nowhere."""
    if settings.DEBUG or settings.ADMINS:
        return []
    return [Warning(
        'ADMIN_EMAILS is empty — server errors, failed backups and a stopped worker alert nobody.',
        hint='Set ADMIN_EMAILS=you@example.com (comma-separated for several) in the server .env.',
        id='ajna.W003',
    )]


@register(Tags.security, deploy=True)
def check_two_factor(app_configs, **kwargs):
    """Staff two-step sign-in (users/two_factor.py) must stay on in production."""
    if settings.DEBUG or settings.STAFF_TWO_FACTOR_REQUIRED:
        return []
    return [Warning(
        'STAFF_TWO_FACTOR_REQUIRED is off — staff sign in with a password alone.',
        hint='Remove STAFF_TWO_FACTOR_REQUIRED=False from the server .env.',
        id='ajna.W004',
    )]
