"""Billing emails: the receipt for every paid payment, a note when a
Fonepay payment fails, and subscription expiry reminders. All go through
send_templated_email, so a mail outage never blocks a payment."""
from django.conf import settings
from django.urls import reverse

from ajna_health_lens.mail import send_templated_email

from .money import format_money


def _absolute(path: str) -> str:
    return f'{settings.SITE_BASE_URL}{path}'


def _seller() -> dict:
    return {
        'legal_name': settings.BUSINESS_LEGAL_NAME, 'pan': settings.BUSINESS_PAN, 'address': settings.BUSINESS_ADDRESS,
    }


def send_receipt(payment) -> bool:
    recipient = payment.payer_email
    if not recipient:
        return False
    receipt_url = _absolute(reverse('billing:receipt', args=[payment.reference])) if payment.user_id else ''
    return send_templated_email(
        subject=f'Receipt {payment.receipt_number} — {payment.description}',
        template='billing/email/receipt',
        context={
            'payment': payment, 'seller': _seller(), 'vat_rate': settings.VAT_RATE.normalize(),
            'receipt_url': receipt_url, 'account_url': _absolute(reverse('billing:account')),
            'subtotal': format_money(payment.subtotal), 'vat': format_money(payment.vat_amount),
            'total': format_money(payment.amount),
        },
        recipient_list=[recipient],
    )


def send_payment_failed(payment, *, underpaid: bool = False) -> bool:
    if not payment.user_id:
        return False
    from .payments import retry_url

    return send_templated_email(
        subject=f'Your payment didn’t go through — {payment.description}',
        template='billing/email/payment_failed',
        context={
            'payment': payment, 'underpaid': underpaid, 'total': format_money(payment.amount),
            'retry_url': _absolute(retry_url(payment)), 'contact_email': settings.JOURNAL_CONTACT_EMAIL,
        },
        recipient_list=[payment.user.email],
    )


def send_subscription_reminder(subscription, stage: str) -> bool:
    """stage: a number of days left ("7", "1") or "ended"."""
    plan = subscription.plan
    days_left = None if stage == 'ended' else int(stage)
    if stage == 'ended':
        subject = f'Your {settings.JOURNAL_NAME} subscription has ended'
    elif days_left == 1:
        subject = f'Your {settings.JOURNAL_NAME} subscription ends tomorrow'
    else:
        subject = f'Your {settings.JOURNAL_NAME} subscription ends in {days_left} days'
    from users.privacy import list_unsubscribe_headers, unsubscribe_url

    stop_url = unsubscribe_url(subscription.user, 'reminders')
    return send_templated_email(
        subject=subject,
        template='billing/email/subscription_reminder',
        headers=list_unsubscribe_headers(stop_url),
        context={
            'subscription': subscription, 'user': subscription.user, 'plan': plan, 'stage': stage,
            'days_left': days_left, 'renew_url': _absolute(reverse('billing:subscribe_checkout', args=[plan.pk])),
            'plans_url': _absolute(reverse('billing:plan_browse')), 'account_url': _absolute(reverse('billing:account')),
            'unsubscribe_url': stop_url,
        },
        recipient_list=[subscription.user.email],
    )


def send_refund_confirmation(payment) -> bool:
    recipient = payment.payer_email
    if not recipient:
        return False
    return send_templated_email(
        subject=f'Refund {payment.credit_note_number} — {payment.description}',
        template='billing/email/refund',
        context={
            'payment': payment, 'seller': _seller(), 'vat_rate': settings.VAT_RATE.normalize(),
            'subtotal': format_money(payment.subtotal), 'vat': format_money(payment.vat_amount),
            'total': format_money(payment.amount), 'contact_email': settings.JOURNAL_CONTACT_EMAIL,
            'receipt_url': _absolute(reverse('billing:receipt', args=[payment.reference])) if payment.user_id else '',
        },
        recipient_list=[recipient],
    )
