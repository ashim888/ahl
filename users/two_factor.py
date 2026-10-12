"""Two-step sign-in (TOTP) for staff.

Every Editor, Editor-in-Chief and Admin (and superuser) signs in with their
password AND a 6-digit code from an authenticator app (Google Authenticator,
Authy, Microsoft Authenticator…). Built on django-otp:

- session_is_verified: whether this session passed two-step sign-in (the
  device django_otp.login stored in the session). django-otp's own
  OTPMiddleware isn't used — it overwrites request.user.is_verified, which
  is a real field on our User model;
- StaffTwoFactorMiddleware: a staff session that hasn't passed two-step
  sign-in is sent to set it up (first time) or to enter a code — before any
  other page, including the dashboard and Django admin;
- setup: scan a QR code, confirm one code, get 10 one-time backup codes;
- verify: an app code or a backup code;
- staff_reset: an Editor-in-Chief/Admin clears a colleague's devices (lost
  phone) — they set it up again at their next sign-in;
- `manage.py reset_two_step <email>` for when nobody can sign in.

Security emails go out when two-step sign-in is turned on or reset, and when
a backup code is used. Switch off only for local development
(STAFF_TWO_FACTOR_REQUIRED=False).
"""
import base64
import logging

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django_otp import DEVICE_ID_SESSION_KEY, match_token
from django_otp import login as otp_login
from django_otp.models import Device
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_ratelimit.decorators import ratelimit

from ajna_health_lens.mail import send_templated_email

logger = logging.getLogger(__name__)

BACKUP_CODE_COUNT = 10
# Paths a staff member may open before passing two-step sign-in.
OPEN_PREFIXES = ('/account/two-step/', '/logout/', '/static/', '/healthz/', '/csp-report/', '/i18n/', '/favicon')


def requires_two_factor(user) -> bool:
    return bool(
        settings.STAFF_TWO_FACTOR_REQUIRED and user.is_authenticated
        and (user.is_superuser or getattr(user, 'is_editorial_staff', False)),
    )


def has_device(user) -> bool:
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def session_is_verified(request) -> bool:
    """Has this session passed two-step sign-in, with a device of this user?"""
    persistent_id = request.session.get(DEVICE_ID_SESSION_KEY) if hasattr(request, 'session') else None
    if not persistent_id or not request.user.is_authenticated:
        return False
    device = Device.from_persistent_id(persistent_id)
    return bool(device and device.user_id == request.user.pk and device.confirmed)


class StaffTwoFactorMiddleware:
    """Sends a staff session that hasn't passed two-step sign-in to set it
    up or enter a code."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and requires_two_factor(user) and not request.path.startswith(OPEN_PREFIXES) \
                and not session_is_verified(request):
            target = 'users:two_step_verify' if has_device(user) else 'users:two_step_setup'
            return redirect(f'{reverse(target)}?next={request.get_full_path()}')
        return self.get_response(request)


def _next_url(request) -> str:
    target = request.POST.get('next') or request.GET.get('next') or ''
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}) and target.startswith('/'):
        return target
    return reverse('admin_custom:dashboard')


def _qr_svg(data: str) -> str:
    image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return image.to_string(encoding='unicode')


def _new_backup_codes(user) -> list[str]:
    device, _ = StaticDevice.objects.get_or_create(user=user, name='Backup codes')
    device.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(BACKUP_CODE_COUNT)]
    StaticToken.objects.bulk_create(StaticToken(device=device, token=code) for code in codes)
    return codes


def _security_email(user, event: str, **extra):
    send_templated_email(
        subject={
            'enabled': f'Two-step sign-in is on for your {settings.JOURNAL_NAME} account',
            'reset': f'Two-step sign-in was reset on your {settings.JOURNAL_NAME} account',
            'backup_code': f'A backup code was used to sign in to {settings.JOURNAL_NAME}',
        }[event],
        template='users/email/two_step_notice',
        context={'user': user, 'event': event, 'contact_email': settings.JOURNAL_CONTACT_EMAIL, **extra},
        recipient_list=[user.email],
    )


@login_required
def setup(request):
    """First time: scan the QR code, confirm with one code, get backup codes."""
    user = request.user
    if has_device(user):
        return redirect(f"{reverse('users:two_step_verify')}?next={_next_url(request)}")
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first() or TOTPDevice.objects.create(
        user=user, name='Authenticator app', confirmed=False,
    )
    error = None
    if request.method == 'POST':
        code = ''.join(request.POST.get('code', '').split())
        if device.verify_token(code):
            device.confirmed = True
            device.save(update_fields=['confirmed'])
            codes = _new_backup_codes(user)
            otp_login(request, device)
            _security_email(user, 'enabled')
            logger.info('Two-step sign-in enabled for %s', user.email)
            return render(request, 'users/two_step_backup_codes.html', {'codes': codes, 'next': _next_url(request)})
        error = _('That code didn’t match. Check the time on your phone is set automatically, and try the newest code.')
    secret = base64.b32encode(device.bin_key).decode()
    return render(request, 'users/two_step_setup.html', {
        'qr_svg': mark_safe(_qr_svg(device.config_url)),
        'secret': ' '.join(secret[i:i + 4] for i in range(0, len(secret), 4)),
        'error': error, 'next': _next_url(request),
    })


@login_required
@ratelimit(key='user', rate='10/m', method='POST', block=False)
def verify(request):
    """Each sign-in: a code from the app, or a backup code."""
    user = request.user
    if not has_device(user):
        return redirect(f"{reverse('users:two_step_setup')}?next={_next_url(request)}")
    if session_is_verified(request):
        return redirect(_next_url(request))
    error = None
    if request.method == 'POST':
        if getattr(request, 'limited', False):
            error = _('Too many attempts — wait a minute and try again.')
        else:
            code = ''.join(request.POST.get('code', '').split())
            device = match_token(user, code) if code else None
            if device is not None:
                otp_login(request, device)
                if isinstance(device, StaticDevice):
                    _security_email(user, 'backup_code', remaining=device.token_set.count())
                    messages.warning(request, _('You signed in with a backup code — each works once. %(n)s left.') % {
                        'n': device.token_set.count()})
                return redirect(_next_url(request))
            logger.warning('Failed two-step code for %s', user.email)
            error = _('That code didn’t work. Try the newest code from your app, or one of your backup codes.')
    return render(request, 'users/two_step_verify.html', {'error': error, 'next': _next_url(request)})


@login_required
@require_POST
def new_backup_codes(request):
    """Replace the backup codes (the old ones stop working)."""
    if not session_is_verified(request) or not has_device(request.user):
        raise PermissionDenied
    codes = _new_backup_codes(request.user)
    return render(request, 'users/two_step_backup_codes.html', {'codes': codes, 'next': reverse('users:privacy')})


@login_required
@require_POST
def staff_reset(request, pk):
    """An Editor-in-Chief/Admin clears a colleague's two-step devices (lost
    phone). Same rule as staff management: only Admins reset Admins."""
    from .models import User

    actor = request.user
    if not actor.is_senior_staff:
        raise PermissionDenied
    target = get_object_or_404(User, pk=pk)
    if target.pk == actor.pk or (target.role == User.Role.ADMIN and actor.role != User.Role.ADMIN):
        raise PermissionDenied
    TOTPDevice.objects.filter(user=target).delete()
    StaticDevice.objects.filter(user=target).delete()
    _security_email(target, 'reset', by=actor.get_full_name() or actor.email)
    logger.info('Two-step sign-in for %s reset by %s', target.email, actor.email)
    messages.success(request, f'Two-step sign-in reset for {target.email} — they set it up again at their next sign-in.')
    return redirect('users:manage_staff_update', pk=target.pk)
