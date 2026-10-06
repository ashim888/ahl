"""{{ keyword.name|hashtag }} and {% article_hashtags article %} — see articles/topics.py."""
from django import template

from articles.topics import hashtag as _hashtag

register = template.Library()


@register.filter
def hashtag(name):
    return _hashtag(str(name))


@register.inclusion_tag('articles/includes/hashtags.html')
def article_hashtags(article, limit=3, extra_class=''):
    """The first `limit` topics of an article as #hashtag links. Uses the
    prefetched keyword_tags when the list view prefetched them."""
    return {'keywords': list(article.keyword_tags.all())[:limit], 'extra_class': extra_class}
