from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import strip_tags


def render_issue_email(subject, body_html, unsubscribe_url, is_preview=False):
    """Renders templates/newsletter/email/issue_email.html — the one real
    branded template used for both an actual send (tasks.py) and the
    editorial preview (views.py:issue_preview), so a subscriber's inbox and
    what an editor previewed can never drift apart. Journal branding is
    passed explicitly rather than relying on the journal_settings context
    processor, since tasks.py runs on a background worker with no request
    to run context processors against.
    """
    return render_to_string('newsletter/email/issue_email.html', {
        'subject': subject,
        'body_html': body_html,
        'unsubscribe_url': unsubscribe_url,
        'is_preview': is_preview,
        'journal_name': settings.JOURNAL_NAME,
        'journal_tagline': settings.JOURNAL_TAGLINE,
        'journal_publisher': settings.JOURNAL_PUBLISHER,
        'journal_contact_email': settings.JOURNAL_CONTACT_EMAIL,
    })


def issue_email_text_body(subject, body_html, unsubscribe_url):
    """Plain-text alternative — strip_tags on the editor's HTML is a blunt
    instrument (no line-break preservation, list markers, etc.) but this is
    only ever the fallback part of a multipart email for the rare client
    that doesn't render HTML at all; the HTML part above is what everyone
    else actually sees.
    """
    return f'{subject}\n\n{strip_tags(body_html)}\n\n---\nUnsubscribe: {unsubscribe_url}'


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
