"""Proving a reader receives mail at their address — needed before an
email domain can unlock organization access (billing/institutions.py).

The link carries a signed "<user id>:<email>" token, valid for
LINK_VALID_DAYS; it only confirms the address it was sent to, so changing
the email afterwards makes an old link useless.
"""
from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone

from ajna_health_lens.mail import send_templated_email

SALT = 'users.email-confirmation'
LINK_VALID_DAYS = 3


def make_token(user) -> str:
    return signing.dumps(f'{user.pk}:{user.email.lower()}', salt=SALT, compress=True)


def user_for_token(token: str):
    """The user the token confirms, or None (bad, expired, or the email has
    changed since it was sent)."""
    from .models import User

    try:
        value = signing.loads(token, salt=SALT, max_age=LINK_VALID_DAYS * 86400)
    except signing.BadSignature:
        return None
    pk, _, email = value.partition(':')
    user = User.objects.filter(pk=pk, is_active=True).first() if pk.isdigit() else None
    if user is None or user.email.lower() != email:
        return None
    return user


def confirm(user) -> None:
    if not user.email_confirmed_at:
        user.email_confirmed_at = timezone.now()
        user.save(update_fields=['email_confirmed_at'])


def send_confirmation(user, organization=None) -> bool:
    url = f"{settings.SITE_BASE_URL}{reverse('users:confirm_email', args=[make_token(user)])}"
    return send_templated_email(
        subject=f'Confirm your email for {settings.JOURNAL_NAME}',
        template='users/email/confirm_email',
        context={'user': user, 'confirm_url': url, 'organization': organization, 'valid_days': LINK_VALID_DAYS},
        recipient_list=[user.email],
    )
