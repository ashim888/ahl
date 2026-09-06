"""Runs on a django_q worker (`python manage.py qcluster`), triggered by
newsletter/views.py's compose view via django_q.tasks.async_task — kept out
of the request/response cycle since a real subscriber list makes this a
send-many-emails loop that would otherwise block a submit.
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.urls import reverse
from django.utils import timezone

from .models import NewsletterIssue, Subscriber


def send_newsletter_issue(issue_id):
    issue = NewsletterIssue.objects.get(pk=issue_id)
    subscribers = Subscriber.objects.filter(status=Subscriber.Status.CONFIRMED)

    # One SMTP connection for the whole run, not one per recipient —
    # send_mail() (the previous approach) opens and closes a fresh
    # connection on every call via its own implicit get_connection(), which
    # is fine for a handful of emails but turns into hundreds of redundant
    # TCP/TLS handshakes against a real ESP at actual subscriber-list scale,
    # and risks hitting a provider's per-connection rate limit well before
    # its per-account send limit.
    connection = get_connection()
    connection.open()

    sent = 0
    try:
        for subscriber in subscribers.iterator():
            unsubscribe_url = f"{settings.SITE_BASE_URL}{reverse('newsletter:unsubscribe', args=[subscriber.unsubscribe_token])}"
            text_body = f'{issue.body_html}\n\n---\nUnsubscribe: {unsubscribe_url}'
            html_body = (
                f'{issue.body_html}<p style="font-size:12px;color:#888;">'
                f'<a href="{unsubscribe_url}">Unsubscribe</a></p>'
            )
            message = EmailMultiAlternatives(
                subject=issue.subject, body=text_body, to=[subscriber.email], connection=connection,
            )
            message.attach_alternative(html_body, 'text/html')
            message.send()
            sent += 1
    finally:
        connection.close()

    issue.sent_at = timezone.now()
    issue.recipient_count = sent
    issue.save(update_fields=['sent_at', 'recipient_count'])
    return sent
