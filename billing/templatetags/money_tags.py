from django import template

from billing.money import format_money

register = template.Library()


@register.filter
def money(amount):
    """{{ plan.price|money }} -> "Rs. 4,999" — see billing/money.py."""
    return format_money(amount)


@register.simple_tag
def vat_breakdown(price):
    """{% vat_breakdown plan.price as bill %} -> bill.price / bill.vat /
    bill.total / bill.rate, for checkout summaries."""
    from django.conf import settings

    from billing.money import vat_breakdown as breakdown

    subtotal, vat, total = breakdown(price or 0)
    return {'price': subtotal, 'vat': vat, 'total': total, 'rate': settings.VAT_RATE.normalize()}
