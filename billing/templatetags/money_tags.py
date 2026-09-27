from django import template

from billing.money import format_money

register = template.Library()


@register.filter
def money(amount):
    """{{ plan.price|money }} -> "Rs. 4,999" — see billing/money.py."""
    return format_money(amount)
