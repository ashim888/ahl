from django import template

from ads.services import get_ad_for_request

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
    wrapper itself must not render at all when there's no active ad (an
    empty sticky bar or bordered box would be a worse UI than nothing), and
    only ad_slot.html's own `{% if ad %}` knows whether that's the case.
    """
    request = context['request']
    return {'ad': get_ad_for_request(request, zone), 'wrapper_class': wrapper_class}
