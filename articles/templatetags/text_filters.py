from django import template

register = template.Library()


@register.filter
def split_comma(value):
    """Split a comma-separated string into a list of trimmed, non-empty parts —
    used to render Article.keywords (a flat CharField) as individual tag pills.
    """
    if not value:
        return []
    return [part.strip() for part in value.split(',') if part.strip()]
