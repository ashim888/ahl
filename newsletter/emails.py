from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import strip_tags

from ajna_health_lens.mail import send_notification_email


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


def _email_context(**extra) -> dict:
    """Shared context for the subscriber emails below — the journal name and
    site URL (email/base.html reads branding itself via email_tags, but the
    plain-text parts and body copy need them too).
    """
    return {'journal_name': settings.JOURNAL_NAME, 'site_url': settings.SITE_BASE_URL, **extra}


def send_confirmation_email(subscriber):
    """Single recipient, sent synchronously at signup time — same pattern as
    users/signals.py's verification-status email. Only the bulk send
    (newsletter/tasks.py) needs the async queue. Uses the safe wrapper since
    this runs inline in the public subscribe() view — the Subscriber row is
    already created by the time this is called, so a transient SMTP failure
    here shouldn't turn a successful signup into a 500.
    """
    confirm_url = f"{settings.SITE_BASE_URL}{reverse('newsletter:confirm', args=[subscriber.confirm_token])}"
    context = _email_context(confirm_url=confirm_url)
    send_notification_email(
        subject=f'Confirm your {settings.JOURNAL_NAME} newsletter subscription',
        message=render_to_string('newsletter/email/confirm_subscription.txt', context),
        html_message=render_to_string('newsletter/email/confirm_subscription.html', context),
        recipient_list=[subscriber.email],
    )


def send_welcome_email(subscriber):
    """Sent once, when a subscriber confirms (views.confirm) — tells them
    what to expect and gives them an unsubscribe link from day one.
    """
    unsubscribe_url = f"{settings.SITE_BASE_URL}{reverse('newsletter:unsubscribe', args=[subscriber.unsubscribe_token])}"
    articles_url = f"{settings.SITE_BASE_URL}{reverse('articles:article_list')}"
    context = _email_context(unsubscribe_url=unsubscribe_url, articles_url=articles_url)
    send_notification_email(
        subject=f'Welcome to the {settings.JOURNAL_NAME} newsletter',
        message=render_to_string('newsletter/email/welcome.txt', context),
        html_message=render_to_string('newsletter/email/welcome.html', context),
        recipient_list=[subscriber.email],
    )
