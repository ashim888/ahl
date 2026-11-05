"""{{ article.published_at|news_time }} — how newsrooms show recency on
cards: "Just now", "12 min ago", "3 hours ago" for the last day, then a date
("Sep 25", with the year once it's not this year). Translated like the rest
of the interface.
"""
from django import template
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import get_language, gettext, ngettext

from billing.nepali import to_bs

register = template.Library()

DEVANAGARI_DIGITS = str.maketrans('0123456789', '०१२३४५६७८९')
# Bikram Sambat months (1 = Baisakh) and weekdays (Python's 0 = Monday), as Nepali papers print them.
BS_MONTHS_NE = ('बैशाख', 'जेठ', 'असार', 'साउन', 'भदौ', 'असोज', 'कात्तिक', 'मंसिर', 'पुस', 'माघ', 'फागुन', 'चैत')
WEEKDAYS_NE = ('सोमबार', 'मंगलबार', 'बुधबार', 'बिहीबार', 'शुक्रबार', 'शनिबार', 'आइतबार')


@register.simple_tag
def dateline(today=None) -> str:
    """Today's date the way a Nepali paper's masthead prints it: the Bikram
    Sambat date in Nepali ("शनिबार, ३१ असोज २०८३"); on English pages the
    AD date with the BS date after it."""
    today = today or timezone.localdate()
    bs = to_bs(today)
    if get_language() == 'ne':
        return local_digits(f'{WEEKDAYS_NE[today.weekday()]}, {bs.day} {BS_MONTHS_NE[bs.month - 1]} {bs.year}')
    return f'{today:%A}, {today.day} {today:%B %Y} · {bs.day} {bs.strftime("%B %Y")} BS'


@register.filter
def dual_date(value, show_time=''):
    """{{ article.published_at|dual_date:"time" }} — an article's date with
    Bikram Sambat first, like the masthead's dateline, and AD after it:
    "१६ कात्तिक २०८३ (नभम्वर १, २०२६)" on Nepali pages, "16 Kartik 2083 BS
    (November 1, 2026)" in English. With "time", the clock time follows
    ("· 3:48 PM") unless it's exactly midnight (a date-only stamp)."""
    if not value:
        return ''
    local = timezone.localtime(value) if timezone.is_aware(value) else value
    bs = to_bs(local)
    ad = date_format(local, 'F j, Y').replace(' ', '\u00a0')  # one piece: a narrow column breaks before "(", not inside it
    if get_language() == 'ne':
        text = f'{bs.day} {BS_MONTHS_NE[bs.month - 1]} {bs.year} ({ad})'
    else:
        text = f'{bs.day} {bs.strftime("%B")} {bs.year} BS ({ad})'
    if show_time and (local.hour, local.minute) != (0, 0):
        # Non-breaking, so a narrow column never strands "· 3:48" or "PM" on a line of its own.
        clock = date_format(local, 'g:i A').replace(' ', '\u00a0')
        text = f'{text}\u00a0·\u00a0{clock}'
    return local_digits(text)


@register.filter(is_safe=True)  # swapping digits can't create markup, so safe input stays safe
def local_digits(value):
    """{{ n|local_digits }} — Devanagari digits on Nepali pages, as Nepali
    print uses; unchanged in English."""
    text = str(value)
    return text.translate(DEVANAGARI_DIGITS) if get_language() == 'ne' else text


@register.filter
def news_time(value):
    return local_digits(_news_time(value)) if value else ''


def _news_time(value):
    if not value:
        return ''
    now = timezone.now()
    delta = now - value
    seconds = delta.total_seconds()
    if seconds < 0:
        # A future time (shouldn't reach readers) — just show the date.
        return date_format(timezone.localtime(value), 'M j')
    if seconds < 60:
        return gettext('Just now')
    if seconds < 3600:
        minutes = int(seconds // 60)
        return ngettext('%(count)d min ago', '%(count)d min ago', minutes) % {'count': minutes}
    if seconds < 86400:
        hours = int(seconds // 3600)
        return ngettext('%(count)d hour ago', '%(count)d hours ago', hours) % {'count': hours}
    local = timezone.localtime(value)
    if local.year == timezone.localtime(now).year:
        return date_format(local, 'M j')
    return date_format(local, 'M j, Y')
