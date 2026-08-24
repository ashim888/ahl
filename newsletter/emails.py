from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse


def send_confirmation_email(subscriber):
    """Single recipient, sent synchronously at signup time — same pattern as
    users/signals.py's verification-status email. Only the bulk send
    (newsletter/tasks.py) needs the async queue.
    """
    confirm_url = f"{settings.SITE_BASE_URL}{reverse('newsletter:confirm', args=[subscriber.confirm_token])}"
    send_mail(
        subject=f'Confirm your {settings.JOURNAL_NAME} newsletter subscription',
        message=(
            f'Confirm your subscription by visiting:\n{confirm_url}\n\n'
            "If you didn't request this, you can ignore this email."
        ),
        from_email=None,
        recipient_list=[subscriber.email],
    )
