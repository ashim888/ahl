"""{{ article.published_at|news_time }} — how newsrooms show recency on
cards: "Just now", "12 min ago", "3 hours ago" for the last day, then a date
("Sep 25", with the year once it's not this year). Translated like the rest
of the interface.
"""
from django import template
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext, ngettext

register = template.Library()


@register.filter
def news_time(value):
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
