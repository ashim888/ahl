"""Single source of truth for "who actually receives this issue" —
newsletter/tasks.py's real send and newsletter/views.py's displayed
subscriber counts both call confirmed_recipients() rather than each
building their own filter, so a send and the count an editor saw on the
compose page before clicking Send can't drift apart.
"""
from django.utils import timezone

from billing.models import UserSubscription

from .models import NewsletterIssue, Subscriber


def confirmed_recipients(audience):
    """ALL (the pre-existing, default behavior) is every confirmed
    Subscriber, unchanged. PREMIUM is confirmed subscribers whose linked
    account currently has an active UserSubscription on a plan with
    grants_premium_newsletter=True — a bare-email subscriber (no linked
    account, see Subscriber.user) can never be premium-eligible, since
    there's no account to check a plan against.
    """
    queryset = Subscriber.objects.filter(status=Subscriber.Status.CONFIRMED)
    if audience == NewsletterIssue.Audience.PREMIUM:
        today = timezone.localdate()
        queryset = queryset.filter(
            user__isnull=False,
            user__subscriptions__status=UserSubscription.Status.ACTIVE,
            user__subscriptions__start_date__lte=today,
            user__subscriptions__end_date__gte=today,
            user__subscriptions__plan__grants_premium_newsletter=True,
        ).distinct()
    return queryset
