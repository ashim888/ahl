import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
TURNSTILE_TIMEOUT_SECONDS = 5


def verify_turnstile(token, remote_ip=None):
    """Verifies a Cloudflare Turnstile response token server-side.

    Returns True (treated as passed) when TURNSTILE_SECRET_KEY isn't
    configured — real keys are added later (see ROADMAP.md) — so
    submissions aren't blocked in dev/CI before then, the same "stub until
    the real credentials exist" pattern billing/gateway.py already uses for
    payments. Once a secret key IS configured, fails closed (returns False)
    on a missing token, a Cloudflare-reported failure, or a network/timeout
    error — a broken CAPTCHA check should never silently let spam through.
    """
    if not settings.TURNSTILE_SECRET_KEY:
        return True
    if not token:
        return False

    data = urllib.parse.urlencode({
        'secret': settings.TURNSTILE_SECRET_KEY,
        'response': token,
        **({'remoteip': remote_ip} if remote_ip else {}),
    }).encode()

    try:
        with urllib.request.urlopen(TURNSTILE_VERIFY_URL, data=data, timeout=TURNSTILE_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False

    return bool(result.get('success'))
