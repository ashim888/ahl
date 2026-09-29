"""Real-gateway checkout (Fonepay) — start a payment, verify it, and grant
access exactly once.

Checkout views call start_payment() and send the reader to the payment page
(QR on desktop, bank-app buttons on mobile). The page, a background job
(verify_pending_payments) and the reader returning all funnel into
verify_payment(), which asks Fonepay for the real status. Only a confirmed
"success" with the right amount grants anything, inside a row lock so two
simultaneous checks can't grant twice.
"""
import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import fonepay
from .models import Payment
from .services import record_purchase, start_subscription

logger = logging.getLogger(__name__)


def uses_fonepay() -> bool:
    return settings.PAYMENT_GATEWAY == 'fonepay'


def start_payment(user, *, kind, amount, description, plan=None, article=None, course=None) -> Payment:
    """Reuses the reader's still-open payment for the same item, otherwise
    asks Fonepay for a new QR. Raises fonepay.FonepayError if that fails."""
    open_payment = Payment.objects.filter(
        user=user, kind=kind, plan=plan, article=article, course=course,
        status=Payment.Status.PENDING, expires_at__gt=timezone.now() + datetime.timedelta(minutes=2),
    ).first()
    if open_payment and open_payment.amount == Decimal(amount):
        return open_payment

    payment = Payment(
        user=user, kind=kind, plan=plan, article=article, course=course, amount=amount,
        description=description[:255], gateway='fonepay',
        expires_at=timezone.now() + datetime.timedelta(minutes=settings.FONEPAY_PAYMENT_TIMEOUT_MINUTES),
    )
    data = fonepay.generate_intent_qr(amount, bill_id=f'{kind}-{user.pk}', reference=payment.reference)
    payment.qr_message = data.get('qrMessage') or data.get('qrString') or ''
    payment.websocket_url = data.get('websocketId') or data.get('thirdpartyQrWebSocketUrl') or ''
    if not payment.qr_message:
        raise fonepay.FonepayError('Fonepay did not return a QR payload.')
    payment.save()
    return payment


def _fulfil(payment: Payment):
    """Grant what was paid for. Called once, inside verify_payment's lock."""
    if payment.kind == Payment.Kind.SUBSCRIPTION:
        start_subscription(payment.user, payment.plan, payment_reference=payment.reference)
    elif payment.kind == Payment.Kind.ARTICLE:
        record_purchase(payment.user, payment.article, payment.amount, payment_reference=payment.reference)
    elif payment.kind == Payment.Kind.COURSE:
        from training.models import Enrollment

        enrollment, created = Enrollment.objects.get_or_create(
            user=payment.user, course=payment.course,
            defaults={'payment_status': Enrollment.PaymentStatus.PAID, 'payment_reference': payment.reference},
        )
        if not created:
            enrollment.status = Enrollment.Status.ACTIVE
            enrollment.payment_status = Enrollment.PaymentStatus.PAID
            enrollment.payment_reference = payment.reference
            enrollment.save(update_fields=['status', 'payment_status', 'payment_reference'])


def verify_payment(payment: Payment) -> Payment:
    """Ask Fonepay for the real status and settle the payment. Safe to call
    any number of times, from anywhere."""
    if payment.status != Payment.Status.PENDING:
        return payment
    try:
        data = fonepay.payment_status(payment.reference)
    except fonepay.FonepayError as exc:
        logger.warning('Fonepay status check failed for %s: %s', payment.reference, exc)
        data = None

    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        if locked.status != Payment.Status.PENDING:
            return locked
        if data is not None:
            locked.gateway_response = data
        state = str((data or {}).get('paymentStatus', '')).lower()
        paid = Decimal(str((data or {}).get('totalTransactionAmount') or (data or {}).get('requestedAmount') or '0'))
        if state == 'success' and paid >= locked.amount:
            locked.status = Payment.Status.SUCCESS
            locked.gateway_trace_id = str(data.get('fonepayTraceId') or '')
            locked.completed_at = timezone.now()
            locked.save()
            _fulfil(locked)
        elif state == 'success':
            # Paid, but less than the price — never grant; flag for staff.
            logger.error('Fonepay payment %s underpaid: %s < %s', locked.reference, paid, locked.amount)
            locked.status = Payment.Status.FAILED
            locked.completed_at = timezone.now()
            locked.save()
        elif state == 'failed':
            locked.status = Payment.Status.FAILED
            locked.completed_at = timezone.now()
            locked.save()
        elif timezone.now() >= locked.expires_at + datetime.timedelta(minutes=5):
            # Well past its window with no success reported: close it. (The
            # grace period covers a payment completed at the last second.)
            locked.status = Payment.Status.EXPIRED
            locked.completed_at = timezone.now()
            locked.save()
        elif data is not None:
            locked.save(update_fields=['gateway_response'])
        return locked


def verify_pending_payments() -> int:
    """Background safety net (every few minutes, qcluster): settles payments
    whose reader closed the page after paying. Returns how many settled."""
    settled = 0
    cutoff = timezone.now() - datetime.timedelta(days=1)
    for payment in Payment.objects.filter(status=Payment.Status.PENDING, created_at__gte=cutoff):
        if verify_payment(payment).status != Payment.Status.PENDING:
            settled += 1
    Payment.objects.filter(status=Payment.Status.PENDING, created_at__lt=cutoff).update(
        status=Payment.Status.EXPIRED, completed_at=timezone.now(),
    )
    return settled


def success_url(payment: Payment) -> str:
    if payment.kind == Payment.Kind.ARTICLE:
        return reverse('articles:article_detail', args=[payment.article.slug])
    if payment.kind == Payment.Kind.COURSE:
        return reverse('training:course_detail', args=[payment.course.pk])
    return reverse('users:profile')


def retry_url(payment: Payment) -> str:
    if payment.kind == Payment.Kind.ARTICLE:
        return reverse('billing:purchase_checkout', args=[payment.article.slug])
    if payment.kind == Payment.Kind.COURSE:
        return reverse('training:course_checkout', args=[payment.course.pk])
    return reverse('billing:subscribe_checkout', args=[payment.plan.pk])
