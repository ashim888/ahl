"""Nepali calendar (Bikram Sambat) for invoices: BS dates, and the fiscal
year — which runs from Shrawan 1 (mid-July) to the end of Asar — that
invoice numbers restart in (billing/payments.py next_receipt_number)."""
import datetime

import nepali_datetime
from django.conf import settings
from django.utils import timezone

SHRAWAN = 4  # fiscal year starts on the 1st of the 4th BS month


def _as_date(value) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def to_bs(value) -> nepali_datetime.date:
    return nepali_datetime.date.from_datetime_date(_as_date(value))


def format_bs(value) -> str:
    """'20 Aswin 2083'."""
    if not value:
        return ''
    bs = to_bs(value)  # (nepali_datetime's strftime has no %-d)
    return f'{bs.day} {bs.strftime("%B %Y")}'


def fiscal_year(value=None) -> str:
    """'2083-84' — the Nepali fiscal year containing `value` (default today)."""
    bs = to_bs(value or timezone.localdate())
    start = bs.year if bs.month >= SHRAWAN else bs.year - 1
    return f'{start}-{str(start + 1)[-2:]}'


def format_invoice_date(value) -> str:
    """The invoice date as INVOICE_DATE_DISPLAY says: 'both' (default) →
    '6 October 2026 (20 Aswin 2083 BS)', 'ad' or 'bs' alone."""
    if not value:
        return ''
    ad = _as_date(value).strftime('%-d %B %Y')
    mode = getattr(settings, 'INVOICE_DATE_DISPLAY', 'both')
    if mode == 'ad':
        return ad
    if mode == 'bs':
        return f'{format_bs(value)} BS'
    return f'{ad} ({format_bs(value)} BS)'
