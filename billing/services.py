"""Shared "how access actually gets granted" logic, used by both the
editorial manual-grant forms (billing/forms.py) and the public self-serve
checkout views — one place computes a subscription's date window so the two
paths can't drift apart.
"""
import datetime

from django.utils import timezone

from .models import ArticlePurchase, UserSubscription


def start_subscription(user, plan, payment_reference=''):
    today = timezone.localdate()
    return UserSubscription.objects.create(
        user=user, plan=plan, status=UserSubscription.Status.ACTIVE,
        start_date=today, end_date=today + datetime.timedelta(days=plan.duration_days),
        payment_reference=payment_reference,
    )


def record_purchase(user, article, amount, payment_reference=''):
    return ArticlePurchase.objects.create(
        user=user, article=article, amount=amount, payment_reference=payment_reference,
    )
