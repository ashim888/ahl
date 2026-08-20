import datetime

from django.conf import settings
from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils import timezone
from django.utils.feedgenerator import Atom1Feed

from .models import Article


class LatestArticlesFeed(Feed):
    title = settings.JOURNAL_NAME
    description = settings.JOURNAL_TAGLINE
    link = '/'

    def items(self):
        return Article.objects.filter(status=Article.Status.PUBLISHED).order_by(
            '-publication_date', '-created_at',
        )[:20]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.abstract

    def item_link(self, item):
        return reverse('articles:article_detail', args=[item.slug])

    def item_pubdate(self, item):
        # publication_date is a plain DateField — Feed requires a
        # timezone-aware datetime, not a date.
        if not item.publication_date:
            return None
        return timezone.make_aware(datetime.datetime.combine(item.publication_date, datetime.time.min))

    def item_author_name(self, item):
        first_author = item.articleauthor_set.select_related('user').first()
        return first_author.user.get_full_name() if first_author else settings.JOURNAL_NAME

    def item_categories(self, item):
        return [item.get_article_type_display()]


class LatestArticlesAtomFeed(LatestArticlesFeed):
    feed_type = Atom1Feed
    subtitle = LatestArticlesFeed.description
