from django import template

from ads.models import AdSettings, AdSlot
from ads.services import get_ad_for_request, is_ad_free_reader

register = template.Library()


@register.inclusion_tag('ads/includes/ad_slot.html', takes_context=True)
def ad_slot(context, zone, wrapper_class=''):
    """Renders one ad placement — the single call site every zone (site
    header, homepage, article page, ...) goes through, so ad selection,
    the ad-free-subscriber check, and impression recording (all in
    ads.services.get_ad_for_request) happen identically everywhere instead
    of being re-implemented per view. `wrapper_class` carries placement-
    specific layout (sticky/fixed positioning, centering, spacing) — it's a
    tag argument rather than CSS on the calling template because the
    wrapper itself must not render at all when there's neither an ad nor a
    placeholder, and only ad_slot.html's own `{% if %}` knows whether
    that's the case.

    An unsold zone renders nothing by default — same as before — unless
    AdSettings.get_solo().show_placeholder_when_empty is on, in which case
    it shows an "Advertise Here" box sized to the zone, *except* for an
    ad-free reader (a subscriber), who never sees one regardless of this
    setting: a placeholder is still an ad-shaped thing occupying the page,
    and "ad-free reading" is a promised perk, not just "no active ads."
    """
    request = context['request']
    ad = get_ad_for_request(request, zone)
    placeholder = None
    if not ad and not is_ad_free_reader(request) and AdSettings.get_solo().show_placeholder_when_empty:
        width, height = AdSlot.ZONE_DIMENSIONS[zone]
        placeholder = {
            'zone_label': AdSlot.Zone(zone).label,
            'width': width,
            'height': height,
            'contact_email': context.get('JOURNAL_CONTACT_EMAIL'),
        }
    return {'ad': ad, 'placeholder': placeholder, 'wrapper_class': wrapper_class}
