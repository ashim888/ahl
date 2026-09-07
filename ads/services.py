"""The `ad_slot` template tag (ads/templatetags/ads_tags.py) is the one call
site every ad placement in the site goes through — one place decides which
ad (if any) fills a zone, so every zone picks and counts consistently.
"""
from django.db.models import F, Q
from django.utils import timezone

from billing.access import user_has_perk

from .models import AdEvent, AdSlot


def is_ad_free_reader(request):
    """True for a reader whose active plan grants ad-free reading — a
    per-plan check (SubscriptionPlan.grants_ad_free_reading), not just "has
    any active subscription": every plan defaults that flag to True, so
    behavior is unchanged until an editor configures a plan without it.
    Split out from get_ad_for_request so the `ad_slot` tag can tell "no ad
    sold for this zone" (may show an "Advertise Here" placeholder, see
    AdSettings) apart from "this reader never sees ads at all" (never a
    placeholder either — a placeholder is still an ad-shaped thing occupying
    the page).
    """
    return request.user.is_authenticated and user_has_perk(request.user, 'grants_ad_free_reading')


def get_ad_for_request(request, zone):
    """None for an ad-free reader — otherwise picks and records one
    impression for `zone`. Deliberately never cached: subscription status
    is per-request, and an impression must be counted on every real view,
    not once per cache TTL.
    """
    if is_ad_free_reader(request):
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
