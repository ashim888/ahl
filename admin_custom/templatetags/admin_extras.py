from django import template

from articles.models import Article

register = template.Library()


@register.simple_tag
def recent_draft_articles(limit=4):
    """For the sidebar's "Draft articles" quick-list, shown on every admin
    page — a simple_tag (not a context processor) so the query only runs
    when the admin dashboard shell actually renders, not on every public page.
    """
    return Article.objects.filter(status=Article.Status.DRAFT).order_by('-updated_at')[:limit]
