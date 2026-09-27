"""Single place that turns an amount into the price text readers see.

Nepali rupees use South Asian digit grouping — the last three digits, then
groups of two: 1,49,999 rather than 149,999. Whole amounts drop the paisa
(Rs. 499); anything else keeps two decimals (Rs. 12.50).
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings


def group_digits(whole: str) -> str:
    """'149999' -> '1,49,999'."""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ','.join(groups + [tail])


def format_money(amount) -> str:
    """'Rs. 1,49,999' / 'Rs. 12.50'. Returns '' for None or a non-number."""
    if amount is None or amount == '':
        return ''
    try:
        value = Decimal(str(amount)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return ''
    sign = '-' if value < 0 else ''
    whole, _, paisa = f'{abs(value):.2f}'.partition('.')
    text = group_digits(whole) + ('' if paisa == '00' else f'.{paisa}')
    return f'{sign}{settings.CURRENCY_SYMBOL} {text}'
