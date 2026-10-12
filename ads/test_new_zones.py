"""The October 2026 ad zones show where they're meant to: homepage mid
banner and phone lower banner, the end of an article, section and topic
pages, and story lists / search / archive / videos."""
import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from articles.models import Article, Keyword, keyword_slug
from sections.models import Section

from .models import AdSlot
from .placements import PLACEMENTS
from .tests import make_ad


def story(title, n, **extra):
    return Article.objects.create(
        title=title, slug=keyword_slug(title), status=Article.Status.PUBLISHED, html_content='<p>Text.</p>',
        abstract='Summary.', published_at=timezone.now() - datetime.timedelta(hours=n), **extra,
    )


class NewZoneTests(TestCase):
    def setUp(self):
        self.section = Section.objects.create(name='Zone Test Section', slug='zone-test-section')
        self.dengue = Keyword.objects.create(name='Dengue', slug='dengue')
        self.stories = [story(f'Dengue story {i}', i, section=self.section) for i in range(8)]
        for article in self.stories:
            article.keyword_tags.add(self.dengue)

    def assertAdOn(self, zone, url, sponsor):
        make_ad(zone=zone, sponsor_name=sponsor)
        response = self.client.get(url)
        self.assertContains(response, sponsor, msg_prefix=url)
        return response

    def test_every_zone_has_a_size_and_a_description(self):
        for zone in AdSlot.Zone.values:
            self.assertIn(zone, AdSlot.ZONE_DIMENSIONS)
            self.assertIn(zone, PLACEMENTS)

    def test_homepage_mid_and_phone_lower_banners(self):
        response = self.assertAdOn(AdSlot.Zone.HOMEPAGE_MID_BANNER, reverse('articles:home'), 'Mid Banner Co')
        self.assertContains(response, 'Phone Lower Co', count=0)
        self.assertAdOn(AdSlot.Zone.MOBILE_LOWER_BANNER, reverse('articles:home'), 'Phone Lower Co')

    def test_end_of_article(self):
        response = self.assertAdOn(AdSlot.Zone.ARTICLE_END, self.stories[0].get_absolute_url(), 'Article End Co')
        html = response.content.decode()
        self.assertLess(html.index('Article End Co'), html.index('id="comments"'))

    def test_section_and_topic_pages_share_one_zone(self):
        self.assertAdOn(AdSlot.Zone.SECTION_BANNER, reverse('sections:section_detail', args=['zone-test-section']), 'Section Co')
        self.assertContains(self.client.get(reverse('articles:topic_detail', args=['dengue'])), 'Section Co')
        page_two = self.client.get(reverse('sections:section_detail', args=['zone-test-section']), {'page': 2})
        if page_two.status_code == 200:  # only when the section has a second page
            self.assertContains(page_two, 'Section Co')

    def test_story_lists_search_archive_and_videos(self):
        make_ad(zone=AdSlot.Zone.LIST_BANNER, sponsor_name='List Co')
        Article.objects.filter(pk=self.stories[-1].pk).update(status=Article.Status.ARCHIVED)
        for url in (reverse('articles:article_list'), reverse('articles:archive_list'),
                    reverse('articles:search') + '?q=dengue'):
            response = self.client.get(url)
            self.assertContains(response, 'List Co', msg_prefix=url)
        story('A video story', 1, article_type=Article.ArticleType.VIDEO, video_url='https://youtu.be/dQw4w9WgXcQ')
        self.assertContains(self.client.get(reverse('articles:video_list')), 'List Co')

    def test_short_list_still_shows_the_banner(self):
        Article.objects.exclude(pk=self.stories[0].pk).delete()
        make_ad(zone=AdSlot.Zone.LIST_BANNER, sponsor_name='Short List Co')
        self.assertContains(self.client.get(reverse('articles:article_list')), 'Short List Co')

    def test_layout_picture_on_the_form_has_every_new_zone(self):
        from users.models import User

        editor = User.objects.create_user(email='zones@example.com', password='pw', first_name='Z', last_name='E',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        page = self.client.get(reverse('ads:manage_adslot_create'))
        for zone in ('homepage_mid_banner', 'mobile_lower_banner', 'article_end', 'section_banner', 'list_banner'):
            self.assertContains(page, f'data-zone-pick="{zone}"')
