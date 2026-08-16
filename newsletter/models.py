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

    subject = models.CharField(max_length=255)
    body_html = models.TextField(help_text='Trusted, editor-authored HTML — same trust model as Article.html_content.')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='newsletter_issues',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    recipient_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.subject
