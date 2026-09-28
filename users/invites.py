"""Account invitations — for accounts created by an editor without a
password (see AccountCreateForm). The invitee gets a one-time link to the
normal password-reset confirm page, where they choose their own password.

Django's PasswordResetForm can't be reused for this: it deliberately skips
accounts without a usable password, which is exactly what an invited
account is until the link is used.
"""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from ajna_health_lens.mail import send_templated_email


def set_password_url(user) -> str:
    """Absolute, single-use link to choose a password (valid for
    PASSWORD_RESET_TIMEOUT, same as a password reset)."""
    path = reverse('users:password_reset_confirm', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
    })
    return f'{settings.SITE_BASE_URL}{path}'


def send_account_invite(user, invited_by=None) -> bool:
    """Emails `user` a link to set their password. Returns whether the send
    succeeded (send_templated_email never raises)."""
    return send_templated_email(
        subject=f'You have an account on {settings.JOURNAL_NAME}',
        template='users/email/account_invite',
        context={
            'user': user,
            'invited_by': invited_by,
            'set_password_url': set_password_url(user),
            'login_url': f"{settings.SITE_BASE_URL}{reverse('users:login')}",
        },
        recipient_list=[user.email],
    )
