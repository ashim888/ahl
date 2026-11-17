import mimetypes

from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site
from django.contrib.syndication.views import Feed, add_domain
from django.urls import reverse
from django.utils.feedgenerator import Atom1Feed, Rss201rev2Feed

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


class PodcastRssFeed(Rss201rev2Feed):
    """RSS 2.0 with the Apple Podcasts (itunes:) tags Apple and Spotify require."""

    def rss_attributes(self):
        return {**super().rss_attributes(), 'xmlns:itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'}

    def add_root_elements(self, handler):
        super().add_root_elements(handler)
        feed = self.feed
        handler.addQuickElement('itunes:author', feed['itunes_author'])
        handler.addQuickElement('itunes:summary', feed['description'])
        handler.addQuickElement('itunes:type', 'episodic')
        handler.addQuickElement('itunes:explicit', 'false')
        handler.startElement('itunes:owner', {})
        handler.addQuickElement('itunes:name', feed['itunes_author'])
        handler.addQuickElement('itunes:email', feed['itunes_email'])
        handler.endElement('itunes:owner')
        if feed['itunes_image']:
            handler.addQuickElement('itunes:image', '', {'href': feed['itunes_image']})
        handler.startElement('itunes:category', {'text': feed['itunes_category']})
        if feed['itunes_subcategory']:
            handler.addQuickElement('itunes:category', '', {'text': feed['itunes_subcategory']})
        handler.endElement('itunes:category')

    def add_item_elements(self, handler, item):
        super().add_item_elements(handler, item)
        handler.addQuickElement('itunes:summary', item['description'])
        handler.addQuickElement('itunes:explicit', 'false')
        if item['itunes_image']:
            handler.addQuickElement('itunes:image', '', {'href': item['itunes_image']})


class PodcastFeed(Feed):
    """/podcasts/feed/ — the feed Apple Podcasts and Spotify list. Free
    (open access) episodes only: the apps fetch the audio without an account,
    so a paywalled episode's file would just be refused."""

    feed_type = PodcastRssFeed

    def get_feed(self, obj, request):
        self.request = request  # enclosure and image addresses must be absolute
        return super().get_feed(obj, request)

    def absolute(self, url):
        """Same domain as the feed's own links (the Sites framework), so every address matches."""
        if not url:
            return ''
        return add_domain(get_current_site(self.request).domain, url, self.request.is_secure())

    def title(self):
        return settings.PODCAST_TITLE

    def description(self):
        return settings.PODCAST_DESCRIPTION

    def link(self):
        return reverse('articles:podcast_list')

    def feed_extra_kwargs(self, obj):
        return {
            'itunes_author': settings.JOURNAL_NAME, 'itunes_email': settings.PODCAST_OWNER_EMAIL,
            'itunes_image': self.absolute(settings.PODCAST_COVER_URL),
            'itunes_category': settings.PODCAST_CATEGORY, 'itunes_subcategory': settings.PODCAST_SUBCATEGORY,
        }

    @property
    def language(self):  # Django reads self.language directly, not as a dynamic attribute
        return settings.PODCAST_LANGUAGE

    def items(self):
        return podcast_episodes().filter(access_type=Article.AccessType.OPEN_ACCESS)[:100]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.summary

    def item_link(self, item):
        return reverse('articles:article_detail', args=[item.slug])

    def item_pubdate(self, item):
        return item.published_at

    def item_guid(self, item):
        return f'ahl-article-{item.pk}'  # stable even if the slug changes

    item_guid_is_permalink = False

    def item_enclosure_url(self, item):
        return self.absolute(item.audio_file.url)

    def item_enclosure_length(self, item):
        try:
            return item.audio_file.size
        except OSError:  # file missing on disk: still list the episode
            return 0

    def item_enclosure_mime_type(self, item):
        return mimetypes.guess_type(item.audio_file.name)[0] or 'audio/mpeg'

    def item_extra_kwargs(self, item):
        return {'itunes_image': self.absolute(item.featured_image.url) if item.featured_image else ''}


def podcast_episodes():
    """Published podcast stories that have their audio, newest first."""
    return (Article.objects.filter(status=Article.Status.PUBLISHED, article_type=Article.ArticleType.PODCAST)
            .exclude(audio_file='').exclude(audio_file__isnull=True).order_by('-published_at', '-created_at'))
