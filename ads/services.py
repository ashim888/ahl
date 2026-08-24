"""Shared by articles/views.py (homepage + article sidebar placements) — one
place decides which ad (if any) fills a zone, so both placements pick and
count consistently.
"""
from django.db.models import F, Q
from django.utils import timezone

from .models import AdEvent, AdSlot


def get_ad_for_zone(zone):
    today = timezone.localdate()
    candidates = AdSlot.objects.filter(
        zone=zone, is_active=True, start_date__lte=today,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
    # order_by('?') for simple rotation across multiple active sponsors in
    # the same zone — fine at this site's scale, not meant to scale to a
    # large ad inventory.
    return candidates.order_by('?').first()


def record_impression(ad_slot):
    AdSlot.objects.filter(pk=ad_slot.pk).update(impression_count=F('impression_count') + 1)
    AdEvent.objects.create(ad_slot=ad_slot, event_type=AdEvent.EventType.IMPRESSION)


def record_click(ad_slot):
    AdSlot.objects.filter(pk=ad_slot.pk).update(click_count=F('click_count') + 1)
    AdEvent.objects.create(ad_slot=ad_slot, event_type=AdEvent.EventType.CLICK)
