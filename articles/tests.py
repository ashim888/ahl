import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Article


def make_article(slug, article_type, status=Article.Status.PUBLISHED, homepage_section='', publication_date=None):
    return Article.objects.create(
        title=slug.replace('-', ' ').title(), slug=slug, abstract='Abstract',
        article_type=article_type, status=status, homepage_section=homepage_section,
        publication_date=publication_date,
    )


class HomeViewSectionCurationTests(TestCase):
    """Article.homepage_section lets an editor override the previously fully
    automatic (most-recent-by-type) homepage section selection — these cover
    curation taking priority, autofill still covering unfilled slots, and no
    article ever appearing in two sections at once.
    """

    def test_explicit_hero_wins_over_most_recent_article(self):
        older = make_article(
            'flagship-research', Article.ArticleType.ORIGINAL_RESEARCH,
            homepage_section=Article.HomepageSection.HERO, publication_date=datetime.date(2026, 1, 1),
        )
        make_article('breaking-news', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 6, 1))

        response = self.client.get(reverse('articles:home'))
        self.assertEqual(response.context['hero_article'], older)

    def test_no_explicit_hero_falls_back_to_most_recent(self):
        make_article('older-piece', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 1, 1))
        newest = make_article('newest-piece', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 6, 1))

        response = self.client.get(reverse('articles:home'))
        self.assertEqual(response.context['hero_article'], newest)

    def test_latest_news_autofills_unfilled_slots(self):
        # An unrelated explicit Hero pick, so Hero's own fallback (no type
        # filter — see pick() in views.py) doesn't compete with Latest News
        # for the same pool of unflagged articles.
        make_article('unrelated-hero', Article.ArticleType.EDITORIAL, homepage_section=Article.HomepageSection.HERO)

        # Only one explicit pick, but the section holds 3 — the other 2
        # slots should still autofill from recent news_commentary articles.
        picked = make_article(
            'curated-news', Article.ArticleType.NEWS_COMMENTARY,
            homepage_section=Article.HomepageSection.LATEST_NEWS, publication_date=datetime.date(2026, 1, 1),
        )
        auto1 = make_article('auto-news-1', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 6, 1))
        auto2 = make_article('auto-news-2', Article.ArticleType.NEWS_COMMENTARY, publication_date=datetime.date(2026, 5, 1))

        response = self.client.get(reverse('articles:home'))
        latest_news = response.context['latest_news']
        self.assertEqual(len(latest_news), 3)
        self.assertIn(picked, latest_news)
        self.assertIn(auto1, latest_news)
        self.assertIn(auto2, latest_news)

    def test_article_never_appears_in_two_sections(self):
        # Explicitly featured as Hero — even though it's also a
        # news_commentary article that would otherwise auto-fill Latest News.
        make_article(
            'dual-candidate', Article.ArticleType.NEWS_COMMENTARY,
            homepage_section=Article.HomepageSection.HERO, publication_date=datetime.date(2026, 6, 1),
        )

        response = self.client.get(reverse('articles:home'))
        hero = response.context['hero_article']
        latest_news = response.context['latest_news']
        self.assertNotIn(hero, latest_news)

    def test_homepage_section_overrides_article_type_routing(self):
        # A news_commentary article explicitly placed in Research Highlights
        # shows up there instead of (or as well as) Latest News.
        override = make_article(
            'reclassified-story', Article.ArticleType.NEWS_COMMENTARY,
            homepage_section=Article.HomepageSection.RESEARCH,
        )

        response = self.client.get(reverse('articles:home'))
        self.assertIn(override, response.context['research_highlights'])
        self.assertNotIn(override, response.context['latest_news'])

    def test_draft_articles_never_selected_even_if_flagged(self):
        make_article(
            'unpublished-hero-pick', Article.ArticleType.NEWS_COMMENTARY,
            status=Article.Status.DRAFT, homepage_section=Article.HomepageSection.HERO,
        )
        response = self.client.get(reverse('articles:home'))
        self.assertIsNone(response.context['hero_article'])


class SEOMetaTagsTests(TestCase):
    """Article pages carry real Open Graph/Twitter Card metadata and
    schema.org NewsArticle structured data — templates/base.html's sitewide
    defaults, overridden per-article by ArticleDetailView.
    """

    def test_article_page_has_og_and_twitter_tags(self):
        article = make_article('meta-tagged-article', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        content = response.content.decode()
        self.assertIn(f'content="{article.title}"', content)  # og:title / twitter:title
        self.assertIn('property="og:type" content="article"', content)
        self.assertIn('name="twitter:card" content="summary_large_image"', content)

    def test_article_page_has_news_article_structured_data(self):
        article = make_article('structured-data-article', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, 'application/ld+json')
        self.assertContains(response, '"@type": "NewsArticle"')
        self.assertContains(response, article.title)

    def test_non_article_page_falls_back_to_sitewide_defaults(self):
        response = self.client.get(reverse('articles:home'))
        content = response.content.decode()
        self.assertIn('property="og:type" content="website"', content)


class FeedSitemapRobotsTests(TestCase):
    def test_rss_feed_lists_published_articles_only(self):
        published = make_article('feed-published', Article.ArticleType.NEWS_COMMENTARY)
        draft = make_article('feed-draft', Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT)
        response = self.client.get(reverse('articles:latest_feed'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(published.title, content)
        self.assertNotIn(draft.title, content)

    def test_atom_feed_renders(self):
        response = self.client.get(reverse('articles:latest_feed_atom'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/atom+xml', response['Content-Type'])

    def test_sitemap_lists_published_articles_only(self):
        published = make_article('sitemap-published', Article.ArticleType.NEWS_COMMENTARY)
        draft = make_article('sitemap-draft', Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT)
        response = self.client.get(reverse('sitemap'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(published.slug, content)
        self.assertNotIn(draft.slug, content)

    def test_robots_txt_disallows_manage_and_points_to_sitemap(self):
        response = self.client.get(reverse('robots_txt'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Disallow: /manage/', content)
        self.assertIn('Sitemap:', content)
        self.assertIn('/sitemap.xml', content)


class EngagementCounterTests(TestCase):
    """citation_count/download_count were migrated fields that nothing ever
    incremented (August 2026 gap audit) — these confirm the real code paths
    that now update them.
    """

    def test_citation_export_increments_citation_count(self):
        article = make_article('cited-article', Article.ArticleType.ORIGINAL_RESEARCH)
        self.assertEqual(article.citation_count, 0)
        self.client.get(reverse('articles:article_citation', args=[article.slug, 'bibtex']))
        self.client.get(reverse('articles:article_citation', args=[article.slug, 'ris']))
        article.refresh_from_db()
        self.assertEqual(article.citation_count, 2)

    def test_pdf_download_increments_download_count_and_redirects(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        article = make_article('downloadable-article', Article.ArticleType.NEWS_COMMENTARY)
        article.pdf_file = SimpleUploadedFile('test.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        article.save()
        self.assertEqual(article.download_count, 0)

        response = self.client.get(reverse('articles:article_download', args=[article.slug]))
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.download_count, 1)

    def test_download_blocked_by_paywall_does_not_increment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        article = make_article('gated-downloadable', Article.ArticleType.ORIGINAL_RESEARCH)
        article.access_type = Article.AccessType.SUBSCRIPTION
        article.pdf_file = SimpleUploadedFile('test.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        article.save()

        response = self.client.get(reverse('articles:article_download', args=[article.slug]))
        self.assertEqual(response.status_code, 404)
        article.refresh_from_db()
        self.assertEqual(article.download_count, 0)


class KeywordBrowsingTests(TestCase):
    def test_keyword_pill_links_to_filtered_list(self):
        article = Article.objects.create(
            title='Tagged Article', slug='tagged-article', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
            keywords='tuberculosis, screening',
        )
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, '?keyword=tuberculosis')

    def test_article_list_filters_by_keyword(self):
        matching = Article.objects.create(
            title='TB Article', slug='tb-article', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
            keywords='tuberculosis, screening',
        )
        other = Article.objects.create(
            title='Unrelated Article', slug='unrelated-article', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
            keywords='maternal health',
        )
        response = self.client.get(reverse('articles:article_list'), {'keyword': 'tuberculosis'})
        articles = list(response.context['articles'])
        self.assertIn(matching, articles)
        self.assertNotIn(other, articles)
        self.assertEqual(response.context['selected_keyword'], 'tuberculosis')


class SearchRelevanceAndRateLimitTests(TestCase):
    def test_title_match_ranks_above_abstract_only_match(self):
        title_match = Article.objects.create(
            title='Tuberculosis Screening Update', slug='title-match', abstract='General health news.',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        )
        abstract_only_match = Article.objects.create(
            title='Health Policy Roundup', slug='abstract-match',
            abstract='Includes a note on tuberculosis screening programs.',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        )
        response = self.client.get(reverse('articles:search'), {'q': 'tuberculosis'})
        results = list(response.context['articles'])
        self.assertEqual(results.index(title_match), 0)
        self.assertLess(results.index(title_match), results.index(abstract_only_match))

    def test_excessive_search_requests_are_rate_limited(self):
        # No password hashing involved (unlike login/register — see
        # users/tests.py) so a 30-request burst is fast enough that the
        # django_ratelimit fixed-window boundary risk is negligible here.
        from django.core.cache import cache
        cache.clear()
        for _ in range(30):
            self.client.get(reverse('articles:search'), {'q': 'health'})
        response = self.client.get(reverse('articles:search'), {'q': 'health'})
        self.assertEqual(response.status_code, 403)


class HomepageCachingTests(TestCase):
    def test_homepage_sections_are_cached_and_invalidated_on_save(self):
        from django.core.cache import cache
        from articles.models import HOME_SECTIONS_CACHE_KEY

        cache.clear()
        self.client.get(reverse('articles:home'))
        self.assertIsNotNone(cache.get(HOME_SECTIONS_CACHE_KEY))

        article = make_article('cache-bust-article', Article.ArticleType.NEWS_COMMENTARY)
        article.save()
        self.assertIsNone(cache.get(HOME_SECTIONS_CACHE_KEY))


class HomepageNewsletterCTATests(TestCase):
    def test_anonymous_visitor_sees_cta(self):
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'FREE NEWSLETTER')

    def test_confirmed_subscriber_does_not_see_cta(self):
        from newsletter.models import Subscriber
        from users.models import User

        reader = User.objects.create_user(email='cta-reader@example.com', password='pw', first_name='C', last_name='R')
        Subscriber.objects.create(user=reader, email=reader.email, status=Subscriber.Status.CONFIRMED)
        self.client.force_login(reader)
        response = self.client.get(reverse('articles:home'))
        self.assertNotContains(response, 'FREE NEWSLETTER')


class ArticleViewTrackingTests(TestCase):
    """First-party page-view tracking (August 2026 decision — no third-party
    analytics vendor). ArticleView rows power the homepage's Trending
    section; see articles/views.py:_record_article_view.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_viewing_an_article_records_a_view(self):
        article = make_article('viewed-article', Article.ArticleType.NEWS_COMMENTARY)
        self.assertEqual(article.page_views.count(), 0)
        self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertEqual(article.page_views.count(), 1)

    def test_repeat_view_in_same_session_is_deduplicated(self):
        article = make_article('deduped-article', Article.ArticleType.NEWS_COMMENTARY)
        for _ in range(3):
            self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertEqual(article.page_views.count(), 1)

    def test_editorial_staff_views_are_not_recorded(self):
        from users.models import User

        editor = User.objects.create_user(
            email='view-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        article = make_article('staff-viewed-article', Article.ArticleType.NEWS_COMMENTARY)
        self.client.force_login(editor)
        self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertEqual(article.page_views.count(), 0)


class TrendingSectionTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_articles_ranked_by_recent_view_count(self):
        from articles.models import ArticleView

        popular = make_article('popular-article', Article.ArticleType.NEWS_COMMENTARY)
        unpopular = make_article('unpopular-article', Article.ArticleType.NEWS_COMMENTARY)
        for i in range(5):
            ArticleView.objects.create(article=popular, session_key=f's{i}')
        ArticleView.objects.create(article=unpopular, session_key='s0')

        response = self.client.get(reverse('articles:home'))
        trending = list(response.context['trending_articles'])
        self.assertEqual(trending[0], popular)
        self.assertIn(unpopular, trending)

    def test_views_older_than_a_week_are_excluded(self):
        import datetime

        from articles.models import ArticleView

        article = make_article('stale-trending-article', Article.ArticleType.NEWS_COMMENTARY)
        old_view = ArticleView.objects.create(article=article, session_key='old')
        ArticleView.objects.filter(pk=old_view.pk).update(
            viewed_at=timezone.now() - datetime.timedelta(days=10),
        )
        response = self.client.get(reverse('articles:home'))
        self.assertNotIn(article, response.context['trending_articles'])

    def test_unpublished_articles_never_trend(self):
        from articles.models import ArticleView

        draft = make_article('draft-trending-article', Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT)
        ArticleView.objects.create(article=draft, session_key='s0')
        response = self.client.get(reverse('articles:home'))
        self.assertNotIn(draft, response.context['trending_articles'])


class AdFreeSubscriberPerkTests(TestCase):
    """"Ad-free reading" is a promised subscriber perk (billing app) —
    articles/views.py:_ad_for_request is the one place that enforces it.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

        import io

        from django.core.files.base import ContentFile
        from PIL import Image

        from ads.models import AdSlot

        buffer = io.BytesIO()
        Image.new('RGB', (10, 10)).save(buffer, format='JPEG')
        self.ad = AdSlot.objects.create(
            sponsor_name='Test Sponsor', zone=AdSlot.Zone.HOMEPAGE,
            image=ContentFile(buffer.getvalue(), name='ad.jpg'), link_url='https://example.com',
        )

    def test_anonymous_visitor_sees_ad(self):
        response = self.client.get(reverse('articles:home'))
        self.assertEqual(response.context['homepage_ad'], self.ad)

    def test_active_subscriber_does_not_see_ad(self):
        from users.models import User
        from billing.models import SubscriptionPlan, UserSubscription

        reader = User.objects.create_user(email='ad-free-reader@example.com', password='pw', first_name='A', last_name='F')
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=5, duration_days=30,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.client.force_login(reader)
        response = self.client.get(reverse('articles:home'))
        self.assertIsNone(response.context['homepage_ad'])

    def test_impression_is_recorded_when_ad_shown(self):
        self.client.get(reverse('articles:home'))
        self.ad.refresh_from_db()
        self.assertEqual(self.ad.impression_count, 1)
