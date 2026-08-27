import secrets

from django.conf import settings
from django.db import models


def generate_token():
    return secrets.token_urlsafe(32)


class Subscriber(models.Model):
    """Works for both an existing account and a bare email address — `user`
    is nullable so a visitor can sign up without registering. Confirmation
    and unsubscribe are both token-based (no login required for either),
    since a bare-email subscriber has no account to log into.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending confirmation'
        CONFIRMED = 'confirmed', 'Confirmed'
        UNSUBSCRIBED = 'unsubscribed', 'Unsubscribed'

    email = models.EmailField(unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='newsletter_subscriptions',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    confirm_token = models.CharField(max_length=64, unique=True, default=generate_token)
    unsubscribe_token = models.CharField(max_length=64, unique=True, default=generate_token)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-subscribed_at']

    def __str__(self):
        return self.email


class NewsletterIssue(models.Model):
    """A single editorial "compose & send" — sent once, to every confirmed
    Subscriber at the time of sending. Sending is async (django_q) — see
    newsletter/tasks.py — so `sent_at`/`recipient_count` are blank until
    the background task finishes.
    """

    class Status(models.TextChoices):
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'
        SENDING = 'sending', 'Sending…'

    subject = models.CharField(max_length=255)
    body_html = models.TextField(help_text='Trusted, editor-authored HTML — same trust model as Article.html_content.')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='newsletter_issues',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    recipient_count = models.PositiveIntegerField(default=0)
    task_id = models.CharField(
        max_length=32, blank=True,
        help_text="django_q Task id for the current/most recent send attempt — lets the editorial "
                   'list distinguish "still sending" from "the background task failed".',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.subject

    def get_send_status(self):
        """'sent' / 'failed' / 'sending' — derived from django_q's own Task
        record rather than a stored field, since django_q already tracks
        success/failure and duplicating that as a synced field risks drift.
        """
        if self.sent_at:
            return self.Status.SENT
        if self.task_id:
            from django_q.models import Task
            task = Task.objects.filter(id=self.task_id).first()
            if task is not None and not task.success:
                return self.Status.FAILED
        return self.Status.SENDING

    def get_failure_reason(self):
        if not self.task_id:
            return None
        from django_q.models import Task
        task = Task.objects.filter(id=self.task_id, success=False).first()
        return task.result if task else None
