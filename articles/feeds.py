from django.conf import settings
from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils.feedgenerator import Atom1Feed

from .models import Article


class LatestArticlesFeed(Feed):
    title = settings.JOURNAL_NAME
    description = settings.JOURNAL_TAGLINE
    link = '/'

    def items(self):
        return Article.objects.filter(status=Article.Status.PUBLISHED).order_by(
            '-published_at', '-created_at',
        )[:20]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.summary

    def item_link(self, item):
        return reverse('articles:article_detail', args=[item.slug])

    def item_pubdate(self, item):
        return item.published_at

    def item_updateddate(self, item):
        return item.last_updated_at

    def item_author_name(self, item):
        first_author = item.articleauthor_set.select_related('author__user').first()
        return first_author.display_name if first_author else settings.JOURNAL_NAME

    def item_categories(self, item):
        return [item.get_article_type_display()]


class LatestArticlesAtomFeed(LatestArticlesFeed):
    feed_type = Atom1Feed
    subtitle = LatestArticlesFeed.description
