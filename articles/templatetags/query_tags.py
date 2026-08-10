from django import template

register = template.Library()


@register.simple_tag
def querystring_without_page(get_params):
    """URL-encoded querystring from a GET QueryDict with 'page' removed —
    used to build pagination links that preserve filters/search terms
    without corrupting values containing '&', '#', etc.
    """
    params = get_params.copy()
    params.pop('page', None)
    return params.urlencode()
