"""Promo codes: launch offers, student pricing, partner deals and free
trials (models.PromoCode / PromoRedemption).

- A **discount code** is entered at checkout (or arrives with a link,
  /redeem/<CODE>/, kept in the session). It takes a percentage or a fixed
  amount off the VAT-exclusive price; VAT is charged on what's left. The
  receipt shows the list price, the code and the discount. A code that takes
  the whole price off grants the item with no payment (Fonepay can't take
  Rs. 0) — recorded as a redemption, no receipt.
- A **trial code** is redeemed at /redeem/: trial_days of trial_plan, free,
  once, for people who have never had a subscription. Nothing renews.
- Conditions are checked again when the reader pays, never only when the
  code is applied. A use is recorded when the payment completes (or at once
  for a free grant), so an abandoned checkout doesn't use up a code.
"""
import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import PromoCode, PromoRedemption, UserSubscription
from .money import vat_breakdown

CENT = Decimal('0.01')
SESSION_KEY = 'promo_code'

# Checkout kinds (Payment.Kind values).
SUBSCRIPTION, ARTICLE, COURSE = 'subscription', 'article', 'course'


class PromoError(Exception):
    """A code that can't be used here — the message is shown to the reader."""


def find(text: str):
    text = (text or '').strip().upper()
    return PromoCode.objects.filter(code=text).first() if text else None


def _uses(code: PromoCode, user=None) -> int:
    redemptions = PromoRedemption.objects.filter(code=code)
    if user is not None:
        redemptions = redemptions.filter(user=user)
    return redemptions.count()


def _domain_matches(code: PromoCode, user) -> bool:
    email_domain = (user.email or '').rsplit('@', 1)[-1].lower()
    return any(email_domain == d or email_domain.endswith(f'.{d}') for d in code.domains)


def has_ever_subscribed(user) -> bool:
    return UserSubscription.objects.filter(user=user).exists()


def check_common(code: PromoCode, user, today=None) -> None:
    """Conditions that apply wherever the code is used."""
    today = today or timezone.localdate()
    if not code.is_active:
        raise PromoError(_('This code is no longer active.'))
    if code.valid_from and today < code.valid_from:
        raise PromoError(_('This code can be used from %(date)s.') % {'date': code.valid_from.strftime('%-d %B %Y')})
    if code.valid_until and today > code.valid_until:
        raise PromoError(_('This code has expired.'))
    if code.max_redemptions is not None and _uses(code) >= code.max_redemptions:
        raise PromoError(_('This code has been fully used.'))
    if code.per_user_limit and _uses(code, user) >= code.per_user_limit:
        raise PromoError(_('You’ve already used this code.'))
    if code.domains:
        if not _domain_matches(code, user):
            raise PromoError(_('This code is only for email addresses at %(domains)s.') % {'domains': ', '.join(code.domains)})
        if not getattr(user, 'email_confirmed_at', None):
            raise PromoError(_('Confirm your email address first (from your Billing page) — this code needs a '
                               'confirmed address.'))
    if code.new_subscribers_only and has_ever_subscribed(user):
        raise PromoError(_('This code is for new subscribers only.'))


def validate(code: PromoCode, user, *, kind: str, plan=None, article=None, course=None) -> None:
    """Raise PromoError unless `code` can take money off this checkout."""
    if code.is_trial:
        raise PromoError(_('This is a free-trial code — activate it on the “Redeem a code” page instead.'))
    check_common(code, user)
    if kind == SUBSCRIPTION:
        if not code.applies_to_subscriptions:
            raise PromoError(_('This code can’t be used on subscriptions.'))
        if plan is not None and code.plans.exists() and not code.plans.filter(pk=plan.pk).exists():
            raise PromoError(_('This code can’t be used on this plan.'))
    elif kind == ARTICLE:
        if not code.applies_to_articles:
            raise PromoError(_('This code can’t be used on special articles.'))
    elif kind == COURSE:
        if not code.applies_to_courses:
            raise PromoError(_('This code can’t be used on training courses.'))
        if course is not None and code.courses.exists() and not code.courses.filter(pk=course.pk).exists():
            raise PromoError(_('This code can’t be used on this course.'))


def discount_for(code: PromoCode, price) -> Decimal:
    """Rupees off a VAT-exclusive price, never more than the price."""
    price = Decimal(str(price)).quantize(CENT)
    if code.percent_off:
        off = (price * Decimal(min(code.percent_off, 100)) / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    elif code.amount_off:
        off = Decimal(str(code.amount_off)).quantize(CENT)
    else:
        off = Decimal('0')
    return min(off, price)


def quote(price, code: PromoCode | None = None) -> dict:
    """What the checkout shows and charges: list price, discount, price
    after discount (VAT-exclusive), VAT and total."""
    list_price = Decimal(str(price or 0)).quantize(CENT)
    discount = discount_for(code, list_price) if code else Decimal('0.00')
    subtotal, vat, total = vat_breakdown(list_price - discount)
    return {
        'code': code, 'list_price': list_price, 'discount': discount, 'price': subtotal, 'vat': vat, 'total': total,
        'is_free': code is not None and subtotal <= 0,
    }


def record(code: PromoCode, user, *, item: str, discount, payment=None) -> PromoRedemption:
    return PromoRedemption.objects.create(
        code=code, user=user, payment=payment, item=item[:255], discount_amount=discount,
    )


@transaction.atomic
def grant_free(code: PromoCode, user, *, kind: str, description: str, discount, plan=None, article=None, course=None):
    """A code that took the whole price off: grant the item, no payment."""
    from .services import record_purchase, start_subscription

    reference = f'PROMO-{code.code}'[:255]
    if kind == SUBSCRIPTION:
        start_subscription(user, plan, payment_reference=reference)
    elif kind == ARTICLE:
        record_purchase(user, article, Decimal('0'), payment_reference=reference)
    elif kind == COURSE:
        from training.models import Enrollment

        enrollment, _ = Enrollment.objects.get_or_create(user=user, course=course)
        enrollment.status = Enrollment.Status.ACTIVE
        enrollment.payment_status = Enrollment.PaymentStatus.PAID
        enrollment.payment_reference = reference
        enrollment.save(update_fields=['status', 'payment_status', 'payment_reference'])
    return record(code, user, item=description, discount=discount)


@transaction.atomic
def redeem_trial(code: PromoCode, user) -> UserSubscription:
    """Start a free trial. Raises PromoError when it can't be used."""
    if not code.is_trial or not code.trial_plan_id:
        raise PromoError(_('This is a discount code — enter it at checkout when you subscribe.'))
    check_common(code, user)
    if has_ever_subscribed(user):
        raise PromoError(_('Free trials are for people who haven’t subscribed before.'))
    today = timezone.localdate()
    subscription = UserSubscription.objects.create(
        user=user, plan=code.trial_plan, status=UserSubscription.Status.ACTIVE, start_date=today,
        end_date=today + datetime.timedelta(days=code.trial_days), payment_reference=f'TRIAL-{code.code}'[:255],
        is_trial=True,
    )
    record(code, user, item=f'{code.trial_days}-day trial — {code.trial_plan.name}', discount=Decimal('0'))
    return subscription


def report(code: PromoCode) -> dict:
    """Uses, paid revenue (before VAT) and discount given, for staff."""
    from django.db.models import Count, Sum

    from .models import Payment

    totals = code.redemptions.aggregate(uses=Count('pk'), discount=Sum('discount_amount'))
    paid = Payment.objects.filter(promo_code=code, status=Payment.Status.SUCCESS).aggregate(
        revenue=Sum('subtotal'), count=Count('pk'),
    )
    return {
        'uses': totals['uses'] or 0, 'discount': totals['discount'] or Decimal('0'),
        'revenue': paid['revenue'] or Decimal('0'), 'paid_count': paid['count'] or 0,
    }
