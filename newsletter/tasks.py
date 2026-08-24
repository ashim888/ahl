"""Runs on a django_q worker (`python manage.py qcluster`), triggered by
newsletter/views.py's compose view via django_q.tasks.async_task — kept out
of the request/response cycle since a real subscriber list makes this a
send-many-emails loop that would otherwise block a submit.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .models import NewsletterIssue, Subscriber


def send_newsletter_issue(issue_id):
    issue = NewsletterIssue.objects.get(pk=issue_id)
    subscribers = Subscriber.objects.filter(status=Subscriber.Status.CONFIRMED)

    sent = 0
    for subscriber in subscribers.iterator():
        unsubscribe_url = f"{settings.SITE_BASE_URL}{reverse('newsletter:unsubscribe', args=[subscriber.unsubscribe_token])}"
        body = (
            f'{issue.body_html}\n\n---\nUnsubscribe: {unsubscribe_url}'
        )
        send_mail(
            subject=issue.subject, message=body, from_email=None,
            recipient_list=[subscriber.email], html_message=(
                f'{issue.body_html}<p style="font-size:12px;color:#888;">'
                f'<a href="{unsubscribe_url}">Unsubscribe</a></p>'
            ),
        )
        sent += 1

    issue.sent_at = timezone.now()
    issue.recipient_count = sent
    issue.save(update_fields=['sent_at', 'recipient_count'])
    return sent
