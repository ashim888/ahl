"""Every payment that buys access goes through here — start it, confirm it,
and grant access exactly once.

Checkout views call start_payment() and send the reader to the payment page
(QR on desktop, bank-app buttons on mobile). The page, a background job
(verify_pending_payments) and the reader returning all funnel into
verify_payment(), which asks Fonepay for the real status. Only a confirmed
"success" for the full amount grants anything, inside a row lock so two
simultaneous checks can't grant twice.

Payments that are already settled when created — staff recording a bank
transfer, or the development stub gateway — go through record_paid_payment().
Either way, complete_payment() is the single place a payment becomes Paid:
it numbers the receipt, grants access and emails the receipt.

Prices are VAT-exclusive; every payment charges price + VAT (money.vat_breakdown).
"""
import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from . import emails, fonepay
from .models import Payment, ReceiptSequence
from .money import vat_breakdown
from .services import record_purchase, start_subscription

logger = logging.getLogger(__name__)


def uses_fonepay() -> bool:
    return settings.PAYMENT_GATEWAY == 'fonepay'


def safe_return_path(path: str) -> str:
    """`path` if it's a path on this site (e.g. the article a reader
    subscribed from), else ''."""
    path = (path or '').strip()
    if path.startswith('/') and not path.startswith('//') and url_has_allowed_host_and_scheme(path, allowed_hosts=None):
        return path[:255]
    return ''


def start_payment(user, *, kind, price, description, plan=None, article=None, course=None, return_path='') -> Payment:
    """Reuses the reader's still-open payment for the same item, otherwise
    asks Fonepay for a new QR for price + VAT. Raises fonepay.FonepayError
    if that fails."""
    subtotal, vat, total = vat_breakdown(price)
    open_payment = Payment.objects.filter(
        user=user, kind=kind, plan=plan, article=article, course=course,
        status=Payment.Status.PENDING, expires_at__gt=timezone.now() + datetime.timedelta(minutes=2),
    ).first()
    if open_payment and open_payment.amount == total:
        if return_path and open_payment.return_path != return_path:
            open_payment.return_path = safe_return_path(return_path)
            open_payment.save(update_fields=['return_path'])
        return open_payment

    payment = Payment(
        user=user, kind=kind, plan=plan, article=article, course=course,
        subtotal=subtotal, vat_amount=vat, amount=total,
        description=description[:255], gateway=Payment.Gateway.FONEPAY, return_path=safe_return_path(return_path),
        expires_at=timezone.now() + datetime.timedelta(minutes=settings.FONEPAY_PAYMENT_TIMEOUT_MINUTES),
    )
    data = fonepay.generate_intent_qr(total, bill_id=f'{kind}-{user.pk}', reference=payment.reference)
    payment.qr_message = data.get('qrMessage') or data.get('qrString') or ''
    payment.websocket_url = data.get('websocketId') or data.get('thirdpartyQrWebSocketUrl') or ''
    if not payment.qr_message:
        raise fonepay.FonepayError('Fonepay did not return a QR payload.')
    payment.save()
    return payment


def _next_number(sequence_name: str, prefix: str) -> str:
    """The next gap-free number in a sequence. Call inside a transaction."""
    sequence, _ = ReceiptSequence.objects.select_for_update().get_or_create(name=sequence_name)
    sequence.last_number += 1
    sequence.save(update_fields=['last_number'])
    return f'{prefix}{sequence.last_number:06d}'


def next_receipt_number() -> str:
    return _next_number('receipts', settings.RECEIPT_PREFIX)


def next_credit_note_number() -> str:
    return _next_number('credit_notes', f'{settings.RECEIPT_PREFIX}CN-')


def seats_taken(course, *, exclude_user=None) -> int:
    """Enrolled (not cancelled) plus checkouts still open — a seat is held
    while someone is paying for it, so two people can't both pay for the
    last one."""
    from training.models import Enrollment

    enrolled = course.enrollments.exclude(status=Enrollment.Status.CANCELLED)
    paying = Payment.objects.filter(
        course=course, kind=Payment.Kind.COURSE, status=Payment.Status.PENDING, expires_at__gt=timezone.now(),
    ).exclude(user__in=enrolled.values('user'))
    if exclude_user is not None:
        enrolled = enrolled.exclude(user=exclude_user)
        paying = paying.exclude(user=exclude_user)
    return enrolled.count() + paying.values('user').distinct().count()


def _flag(payment: Payment, reason: str):
    """Mark a paid payment for staff to look at (see Payment.attention)."""
    logger.error('Payment %s needs attention: %s', payment.reference, reason)
    payment.attention = reason[:255]
    payment.save(update_fields=['attention'])


def _fulfil(payment: Payment):
    """Grant what was paid for. Called once, from complete_payment. Never
    fails for a business reason — the money is already taken — but flags
    the payment (Payment.attention) when staff should look, and maybe refund."""
    if payment.kind == Payment.Kind.SUBSCRIPTION:
        start_subscription(payment.user, payment.plan, payment_reference=payment.reference)
    elif payment.kind == Payment.Kind.ARTICLE:
        from .models import ArticlePurchase

        if ArticlePurchase.objects.filter(user=payment.user, article=payment.article).exists():
            # Paid twice (two tabs, or a staff grant in the meantime).
            _flag(payment, 'Reader already owned this article — refund this payment?')
        else:
            record_purchase(payment.user, payment.article, payment.subtotal, payment_reference=payment.reference)
    elif payment.kind == Payment.Kind.COURSE:
        from training.models import Enrollment

        course = payment.course
        enrollment = Enrollment.objects.filter(user=payment.user, course=course).first()
        if (enrollment and enrollment.status != Enrollment.Status.CANCELLED
                and enrollment.payment_status == Enrollment.PaymentStatus.PAID):
            _flag(payment, 'Reader was already enrolled and paid for this course — refund this payment?')
            return
        if course.max_enrollments is not None and course.enrollments.exclude(
            status=Enrollment.Status.CANCELLED,
        ).exclude(user=payment.user).count() >= course.max_enrollments:
            # They paid, so they're in — but the course is now over capacity.
            _flag(payment, f'Course was full ({course.max_enrollments} seats) — enrolled over capacity.')
        if enrollment:
            enrollment.status = Enrollment.Status.ACTIVE
            enrollment.payment_status = Enrollment.PaymentStatus.PAID
            enrollment.payment_reference = payment.reference
            enrollment.save(update_fields=['status', 'payment_status', 'payment_reference'])
        else:
            Enrollment.objects.create(
                user=payment.user, course=course,
                payment_status=Enrollment.PaymentStatus.PAID, payment_reference=payment.reference,
            )
    # INSTITUTIONAL: the organization's access is set up by staff on the
    # Organization itself; the payment is the money record only.


def complete_payment(payment: Payment, *, grant: bool = True) -> Payment:
    """Mark a (locked or brand-new) payment Paid: receipt number, access,
    and — once the transaction commits — the receipt email. `grant=False`
    when the caller has already granted access itself (a staff grant form)."""
    payment.status = Payment.Status.SUCCESS
    payment.completed_at = payment.completed_at or timezone.now()
    payment.receipt_number = next_receipt_number()
    payment.billed_name = payment.payer_name[:255]
    payment.billed_email = payment.payer_email
    payment.save()
    if grant:
        _fulfil(payment)
    transaction.on_commit(lambda: emails.send_receipt(payment))
    return payment


@transaction.atomic
def record_paid_payment(*, user=None, organization=None, kind, description, gateway, price=None, total_paid=None,
                        plan=None, article=None, course=None, reference='', recorded_by=None, grant=True,
                        return_path='') -> Payment:
    """A payment that is already settled — staff recording money received
    (gateway=manual, `total_paid` VAT included) or the development stub
    gateway (`price`, VAT added on top). Numbers, grants and emails it."""
    from .money import split_vat_inclusive

    subtotal, vat, total = split_vat_inclusive(total_paid) if total_paid is not None else vat_breakdown(price)
    payment = Payment(
        user=user, organization=organization, kind=kind, plan=plan, article=article, course=course,
        subtotal=subtotal, vat_amount=vat, amount=total, description=description[:255], gateway=gateway,
        expires_at=timezone.now(), recorded_by=recorded_by, return_path=safe_return_path(return_path),
    )
    if reference:
        payment.reference = reference[:30]
    return complete_payment(payment, grant=grant)


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
            locked.gateway_trace_id = str(data.get('fonepayTraceId') or '')
            complete_payment(locked)
        elif state in ('success', 'failed'):
            if state == 'success':
                # Paid, but less than the total — never grant; flag for staff.
                logger.error('Fonepay payment %s underpaid: %s < %s', locked.reference, paid, locked.amount)
            locked.status = Payment.Status.FAILED
            locked.completed_at = timezone.now()
            locked.save()
            transaction.on_commit(lambda: emails.send_payment_failed(locked, underpaid=state == 'success'))
        elif timezone.now() >= locked.expires_at + datetime.timedelta(minutes=5):
            # Well past its window with no success reported: close it. (The
            # grace period covers a payment completed at the last second.)
            # No email — an abandoned QR isn't news to the reader.
            locked.status = Payment.Status.EXPIRED
            locked.completed_at = timezone.now()
            locked.save()
        elif data is not None:
            locked.save(update_fields=['gateway_response'])
        return locked


class RefundError(Exception):
    """A refund that can't be recorded (the payment isn't a paid one)."""


@transaction.atomic
def refund_payment(payment: Payment, *, by, reason: str) -> Payment:
    """Record a full refund made outside the site (bank transfer, Fonepay
    merchant portal) and take back what the payment bought: the
    subscription is cancelled, the article purchase removed, the course
    enrollment cancelled. Issues a credit note number and, after commit,
    emails the payer."""
    from training.models import Enrollment

    from .models import ArticlePurchase, UserSubscription

    locked = Payment.objects.select_for_update().get(pk=payment.pk)
    if locked.status != Payment.Status.SUCCESS:
        raise RefundError(f'Only a paid payment can be refunded (this one is {locked.get_status_display().lower()}).')
    if locked.kind == Payment.Kind.SUBSCRIPTION:
        UserSubscription.objects.filter(payment_reference=locked.reference).update(status=UserSubscription.Status.CANCELLED)
    elif locked.kind == Payment.Kind.ARTICLE:
        ArticlePurchase.objects.filter(payment_reference=locked.reference).delete()
    elif locked.kind == Payment.Kind.COURSE:
        Enrollment.objects.filter(payment_reference=locked.reference).update(
            status=Enrollment.Status.CANCELLED, payment_status=Enrollment.PaymentStatus.REFUNDED,
        )
    locked.status = Payment.Status.REFUNDED
    locked.refunded_at = timezone.now()
    locked.refunded_by = by
    locked.refund_reason = reason
    locked.credit_note_number = next_credit_note_number()
    locked.attention = ''
    locked.save()
    transaction.on_commit(lambda: emails.send_refund_confirmation(locked))
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
    if payment.return_path:
        return payment.return_path
    if payment.kind == Payment.Kind.ARTICLE:
        return reverse('articles:article_detail', args=[payment.article.slug])
    if payment.kind == Payment.Kind.COURSE:
        return reverse('training:course_detail', args=[payment.course.pk])
    return reverse('billing:account')


def retry_url(payment: Payment) -> str:
    if payment.kind == Payment.Kind.ARTICLE:
        return reverse('billing:purchase_checkout', args=[payment.article.slug])
    if payment.kind == Payment.Kind.COURSE:
        return reverse('training:course_checkout', args=[payment.course.pk])
    return reverse('billing:subscribe_checkout', args=[payment.plan.pk])
