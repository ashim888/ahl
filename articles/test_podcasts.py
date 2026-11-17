"""The podcast page and the feed Apple Podcasts and Spotify read."""
import shutil
import tempfile
from xml.etree import ElementTree

from django.contrib.sites.models import Site
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Article

ITUNES = '{http://www.itunes.com/dtds/podcast-1.0.dtd}'
MP3 = b'ID3' + b'\x00' * 997


@override_settings(PODCAST_COVER_URL='/static/images/podcast-cover.jpg', PODCAST_OWNER_EMAIL='pod@example.com')
class PodcastTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        override = override_settings(PRIVATE_MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        self.free = self.episode('Episode 1: dengue myths')
        self.paid = self.episode('Episode 2: members only', access_type=Article.AccessType.SUBSCRIPTION)
        Article.objects.create(title='No audio yet', status=Article.Status.PUBLISHED,
                               article_type=Article.ArticleType.PODCAST)

    def episode(self, title, **extra):
        article = Article.objects.create(title=title, status=Article.Status.PUBLISHED, abstract='About it.',
                                         article_type=Article.ArticleType.PODCAST, **extra)
        article.audio_file.save('ep.mp3', ContentFile(MP3))
        return article

    def test_page_lists_episodes_with_audio(self):
        response = self.client.get(reverse('articles:podcast_list'))
        self.assertEqual(list(response.context['episodes']), [self.paid, self.free])
        self.assertContains(response, reverse('articles:podcast_feed'))

    def test_feed_has_free_episodes_with_playable_audio_and_apple_tags(self):
        response = self.client.get(reverse('articles:podcast_feed'))
        channel = ElementTree.fromstring(response.content).find('channel')
        self.assertEqual(channel.find(f'{ITUNES}owner/{ITUNES}email').text, 'pod@example.com')
        domain = f'http://{Site.objects.get_current().domain}'
        self.assertEqual(channel.find(f'{ITUNES}image').get('href'), f'{domain}/static/images/podcast-cover.jpg')
        self.assertEqual(channel.find(f'{ITUNES}category').get('text'), 'Health & Fitness')
        items = channel.findall('item')
        self.assertEqual([i.find('title').text for i in items], ['Episode 1: dengue myths'])  # free only
        enclosure = items[0].find('enclosure')
        self.assertEqual(enclosure.get('length'), str(len(MP3)))
        self.assertEqual(enclosure.get('type'), 'audio/mpeg')
        url = enclosure.get('url')
        self.assertTrue(url.startswith(f'{domain}/protected-media/'))
        # Podcast apps fetch it without an account.
        self.assertEqual(self.client.get(url.removeprefix(domain)).status_code, 200)
