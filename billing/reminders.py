"""Subscription expiry reminders — Fonepay payments are one-off, so nothing
renews by itself and readers need telling. Runs daily on the qcluster worker
(migration 0010_subscription_reminder_schedule).

For each subscription: an email SUBSCRIPTION_REMINDER_DAYS before it ends
(7 and 1 by default) and one the day after it has ended — unless the reader
has already renewed (a later subscription exists). Each email goes once
(UserSubscription.reminders_sent); if the job misses a day, only the most
urgent outstanding reminder is sent, never a burst of stale ones.
"""
import datetime
import logging

from django.conf import settings
from django.utils import timezone

from .emails import send_subscription_reminder
from .models import UserSubscription

logger = logging.getLogger(__name__)

# How long after ending an "ended" email still makes sense.
ENDED_NOTICE_WINDOW_DAYS = 3


def _renewed(subscription) -> bool:
    return UserSubscription.objects.filter(
        user=subscription.user, status=UserSubscription.Status.ACTIVE, end_date__gt=subscription.end_date,
    ).exclude(pk=subscription.pk).exists()


def _stage_due(subscription, today) -> tuple[str | None, list[str]]:
    """(stage to send now or None, every stage to mark as done)."""
    sent = set(subscription.reminders_sent or [])
    days_left = (subscription.end_date - today).days
    if days_left < 0:
        if 'ended' in sent or -days_left > ENDED_NOTICE_WINDOW_DAYS:
            return None, []
        return 'ended', ['ended']
    due = sorted(n for n in settings.SUBSCRIPTION_REMINDER_DAYS if days_left <= n)
    if not due or str(due[0]) in sent:
        return None, []
    # The most urgent one; the earlier (larger) ones are now pointless.
    return str(due[0]), [str(n) for n in due]


def send_subscription_reminders() -> int:
    """Returns how many reminder emails were sent."""
    today = timezone.localdate()
    furthest = max(settings.SUBSCRIPTION_REMINDER_DAYS)
    candidates = UserSubscription.objects.filter(
        status=UserSubscription.Status.ACTIVE,
        end_date__gte=today - datetime.timedelta(days=ENDED_NOTICE_WINDOW_DAYS),
        end_date__lte=today + datetime.timedelta(days=furthest),
        start_date__lte=today,
    ).select_related('user', 'plan')
    sent_count = 0
    for subscription in candidates:
        stage, mark = _stage_due(subscription, today)
        if stage is None or _renewed(subscription) or not subscription.user.is_active:
            continue
        if not subscription.user.email_renewal_reminders:
            # Switched off on /account/privacy/ or via the email's link.
            continue
        if send_subscription_reminder(subscription, stage):
            sent_count += 1
        # Marked even if the mail server failed: a reader getting no reminder
        # beats getting the same one every day.
        subscription.reminders_sent = sorted(set(subscription.reminders_sent or []) | set(mark))
        subscription.save(update_fields=['reminders_sent'])
    logger.info('Sent %s subscription reminder(s).', sent_count)
    return sent_count
