"""The `ad_slot` template tag (ads/templatetags/ads_tags.py) is the one call
site every ad placement in the site goes through — one place decides which
ad (if any) fills a zone, so every zone picks and counts consistently.
"""
from django.db.models import F, Q
from django.utils import timezone

from billing.access import user_has_active_subscription

from .models import AdEvent, AdSlot


def get_ad_for_request(request, zone):
    """None for a reader with an active subscription — "ad-free reading" is
    a promised subscriber perk (billing app) — otherwise picks and records
    one impression for `zone`. Deliberately never cached: subscription
    status is per-request, and an impression must be counted on every real
    view, not once per cache TTL.
    """
    if request.user.is_authenticated and user_has_active_subscription(request.user):
        return None
    ad = get_ad_for_zone(zone)
    if ad:
        record_impression(ad)
    return ad


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
