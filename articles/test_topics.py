"""Topics (#hashtags): topic pages, the topic index, hashtags on cards and
article pages, trending topics on the homepage, Nepali tags, following, the
sitemap — plus the article share buttons (Facebook/WhatsApp/X/LinkedIn)."""
import datetime

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import User

from .forms import TagifyKeywordsField
from .models import Article, Keyword, KeywordFollow, keyword_slug
from .topics import hashtag, related_topics, trending_topics


def make_article(title, keywords=(), status=Article.Status.PUBLISHED, days_ago=1):
    article = Article.objects.create(
        title=title, slug=keyword_slug(title)[:50], status=status, html_content='<p>x</p>', abstract='A summary.',
        published_at=timezone.now() - datetime.timedelta(days=days_ago),
    )
    article.keyword_tags.set([Keyword.objects.get_or_create(slug=keyword_slug(k), defaults={'name': k})[0]
                              for k in keywords])
    return article


class HashtagTests(TestCase):
    def test_hashtag_formats(self):
        self.assertEqual(hashtag('Type 2 Diabetes'), '#Type2Diabetes')
        self.assertEqual(hashtag('mental health'), '#MentalHealth')
        self.assertEqual(hashtag('HIV'), '#HIV')
        self.assertEqual(hashtag('मानसिक स्वास्थ्य'), '#मानसिक_स्वास्थ्य')
        self.assertEqual(hashtag(''), '')

    def test_nepali_keywords_get_a_slug_and_are_no_longer_dropped(self):
        self.assertEqual(keyword_slug('मानसिक स्वास्थ्य'), 'मानसिक-स्वास्थ्य')
        self.assertEqual(keyword_slug('Type 2 Diabetes'), 'type-2-diabetes')
        keywords = TagifyKeywordsField().clean('डेंगु, Dengue')
        self.assertEqual(sorted(k.slug for k in keywords), ['dengue', 'डेंगु'])


class TopicPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.dengue = make_article('Dengue cases rise', ['Dengue', 'Monsoon'])
        make_article('Dengue vaccine trial', ['Dengue'])
        make_article('Draft about dengue', ['Dengue', 'Secret draft tag'], status=Article.Status.DRAFT)

    def test_topic_page_lists_published_stories(self):
        response = self.client.get(reverse('articles:topic_detail', args=['dengue']))
        self.assertContains(response, '<span>Dengue</span>')
        self.assertContains(response, 'Dengue cases rise')
        self.assertNotContains(response, 'Draft about dengue')
        self.assertEqual(response.context['total'], 2)
        self.assertEqual(response.context['meta_robots'], 'index, follow')
        self.assertIn(Keyword.objects.get(slug='monsoon'), response.context['related'])

    def test_draft_only_and_unknown_topics_are_404(self):
        self.assertEqual(self.client.get(reverse('articles:topic_detail', args=['secret-draft-tag'])).status_code, 404)
        self.assertEqual(self.client.get(reverse('articles:topic_detail', args=['nope'])).status_code, 404)

    def test_thin_topic_is_noindex(self):
        response = self.client.get(reverse('articles:topic_detail', args=['monsoon']))
        self.assertEqual(response.context['meta_robots'], 'noindex, follow')

    def test_nepali_topic_page(self):
        make_article('Mental health in Nepal', ['मानसिक स्वास्थ्य'])
        response = self.client.get(reverse('articles:topic_detail', args=['मानसिक-स्वास्थ्य']))
        self.assertContains(response, 'मानसिक_स्वास्थ्य')

    def test_topic_index_groups_and_trending(self):
        response = self.client.get(reverse('articles:topic_list'))
        self.assertContains(response, 'topic-pill__name">Dengue<')
        self.assertNotContains(response, 'SecretDraftTag')
        self.assertEqual(response.context['topic_count'], 2)

    def test_article_page_and_cards_show_hashtags(self):
        response = self.client.get(self.dengue.get_absolute_url())
        self.assertContains(response, f'href="{reverse("articles:topic_detail", args=["dengue"])}"')
        listing = self.client.get(reverse('articles:article_list'))
        self.assertContains(listing, 'topic-pill__name">Monsoon<')

    def test_homepage_trending_topics(self):
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'TRENDING TOPICS')
        self.assertContains(response, 'topic-pill--hot')  # the top three
        self.assertContains(response, 'topic-pill__rank">01<')
        self.assertContains(response, reverse('articles:topic_detail', args=['dengue']))

    def test_trending_prefers_recent_and_related_counts(self):
        make_article('Old cholera story', ['Cholera'], days_ago=200)
        trending = trending_topics(1)
        self.assertEqual(trending[0].slug, 'dengue')
        self.assertEqual([k.slug for k in related_topics(Keyword.objects.get(slug='dengue'))], ['monsoon'])

    def test_search_suggests_matching_topics(self):
        response = self.client.get(reverse('articles:search'), {'q': 'dengue'})
        self.assertIn(Keyword.objects.get(slug='dengue'), response.context['matching_topics'])

    def test_sitemap_lists_indexable_topics_only(self):
        body = self.client.get('/sitemap.xml').content.decode()
        self.assertIn('/topics/dengue/', body)
        self.assertNotIn('/topics/monsoon/', body)
        self.assertIn('/topics/', body)

    def test_keyword_filter_list_points_canonical_at_topic_page(self):
        response = self.client.get(reverse('articles:article_list'), {'keyword': 'dengue'})
        self.assertTrue(response.context['canonical_url'].endswith(reverse('articles:topic_detail', args=['dengue'])))

    def test_follow_from_topic_page_returns_there(self):
        reader = User.objects.create_user(email='r@example.com', password='pw', first_name='R', last_name='S')
        self.client.force_login(reader)
        url = reverse('articles:topic_detail', args=['dengue'])
        response = self.client.post(reverse('articles:keyword_follow_toggle', args=['dengue']), {'next': url})
        self.assertRedirects(response, url)
        self.assertTrue(KeywordFollow.objects.filter(user=reader, keyword__slug='dengue').exists())
        response = self.client.post(reverse('articles:keyword_follow_toggle', args=['dengue']),
                                    {'next': 'https://evil.example/'})
        self.assertRedirects(response, url)  # unsafe next ignored → topic page


class ShareButtonTests(TestCase):
    def test_facebook_whatsapp_x_linkedin_and_canonical_url(self):
        article = make_article('Share me', ['Dengue'])
        response = self.client.get(article.get_absolute_url() + '?gift=secret-token')
        for network in ('facebook', 'whatsapp', 'x', 'linkedin', 'native'):
            self.assertContains(response, f'data-share="{network}"')
        self.assertContains(response, 'facebook.com/sharer/sharer.php')
        self.assertNotContains(response, "var pageUrl = window.location.href")
