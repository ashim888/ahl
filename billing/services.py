"""Shared "how access actually gets granted" logic, used by both the
editorial manual-grant forms (billing/forms.py) and the public self-serve
checkout views — one place computes a subscription's date window so the two
paths can't drift apart.
"""
import datetime

from django.utils import timezone

from .models import ArticlePurchase, UserSubscription


def paid_through(user):
    """The last day the user's own subscriptions (current or already
    bought for later) cover, or None when nothing current or upcoming."""
    latest = UserSubscription.objects.filter(
        user=user, status=UserSubscription.Status.ACTIVE, end_date__gte=timezone.localdate(),
    ).order_by('-end_date').values_list('end_date', flat=True).first()
    return latest


def next_start_date(user):
    """When a subscription bought now starts: today, or — for a renewal or a
    plan switch bought before the current one runs out — the day after the
    current one ends, so no paid day is lost."""
    current_end = paid_through(user)
    today = timezone.localdate()
    return current_end + datetime.timedelta(days=1) if current_end and current_end >= today else today


def start_subscription(user, plan, payment_reference=''):
    start = next_start_date(user)
    return UserSubscription.objects.create(
        user=user, plan=plan, status=UserSubscription.Status.ACTIVE,
        start_date=start, end_date=start + datetime.timedelta(days=plan.duration_days),
        payment_reference=payment_reference,
    )


def record_purchase(user, article, amount, payment_reference=''):
    return ArticlePurchase.objects.create(
        user=user, article=article, amount=amount, payment_reference=payment_reference,
    )
