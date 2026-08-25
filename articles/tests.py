import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .citations import linkify_citations
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

    def test_keyword_search_box_prefills_current_keyword(self):
        response = self.client.get(reverse('articles:article_list'), {'keyword': 'tuberculosis'})
        self.assertContains(response, 'value="tuberculosis"')

    def test_type_pill_preserves_active_keyword_filter(self):
        response = self.client.get(reverse('articles:article_list'), {'keyword': 'tuberculosis'})
        self.assertContains(response, '&keyword=tuberculosis')


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


class HomepagePitchCTATests(TestCase):
    """A visible on-page banner (not just the nav link) — unconditional
    now that pitch submission itself has no login requirement (August
    2026), so it's the same for every visitor regardless of account state.
    """

    def test_anonymous_visitor_sees_cta(self):
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'PITCH A STORY')
        self.assertContains(response, reverse('pitches:pitch_create'))

    def test_verified_author_sees_cta(self):
        from users.models import User

        author = User.objects.create_user(
            email='home-pitch-author@example.com', password='pw', first_name='A', last_name='U',
            role=User.Role.VERIFIED_AUTHOR,
        )
        self.client.force_login(author)
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'PITCH A STORY')

    def test_editorial_staff_also_sees_cta(self):
        from users.models import User

        editor = User.objects.create_user(
            email='home-pitch-editor@example.com', password='pw', first_name='E', last_name='D',
            role=User.Role.EDITOR,
        )
        self.client.force_login(editor)
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'PITCH A STORY')


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


class ArticleDetailTrendingSidebarTests(TestCase):
    """The article detail page sidebar shows the same "trending this week"
    ranking as the homepage (see _trending_articles, shared by both views)
    — minus the article currently being viewed.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_trending_articles_shown_in_sidebar(self):
        from articles.models import ArticleView

        viewed = make_article('sidebar-trending-viewed', Article.ArticleType.NEWS_COMMENTARY)
        popular = make_article('sidebar-trending-popular', Article.ArticleType.NEWS_COMMENTARY)
        for i in range(3):
            ArticleView.objects.create(article=popular, session_key=f's{i}')

        response = self.client.get(reverse('articles:article_detail', args=[viewed.slug]))
        trending = list(response.context['trending_articles'])
        self.assertIn(popular, trending)
        self.assertContains(response, 'TRENDING THIS WEEK')

    def test_current_article_excluded_from_its_own_trending_list(self):
        from articles.models import ArticleView

        viewed = make_article('sidebar-trending-self', Article.ArticleType.NEWS_COMMENTARY)
        for i in range(5):
            ArticleView.objects.create(article=viewed, session_key=f's{i}')

        response = self.client.get(reverse('articles:article_detail', args=[viewed.slug]))
        self.assertNotIn(viewed, list(response.context['trending_articles']))

    def test_no_trending_section_when_nothing_is_trending(self):
        article = make_article('sidebar-no-trending', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertNotContains(response, 'TRENDING THIS WEEK')


class AdFreeSubscriberPerkTests(TestCase):
    """"Ad-free reading" is a promised subscriber perk (billing app) —
    ads.services.get_ad_for_request (called from the `ad_slot` template tag,
    ads/templatetags/ads_tags.py) is the one place that enforces it. See
    ads/tests.py:AdSlotTemplateTagTests for the general "ad renders and
    records an impression" coverage — this class is scoped to the
    subscriber-perk behavior specifically.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

        import io

        from django.core.files.base import ContentFile
        from PIL import Image

        from ads.models import AdSlot

        buffer = io.BytesIO()
        Image.new('RGB', (300, 250)).save(buffer, format='JPEG')
        self.ad = AdSlot.objects.create(
            sponsor_name='Test Sponsor', zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1,
            image=ContentFile(buffer.getvalue(), name='ad.jpg'), link_url='https://example.com',
        )

    def test_anonymous_visitor_sees_ad(self):
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'Test Sponsor')

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
        self.assertNotContains(response, 'Test Sponsor')

    def test_impression_is_recorded_when_ad_shown(self):
        self.client.get(reverse('articles:home'))
        self.ad.refresh_from_db()
        self.assertEqual(self.ad.impression_count, 1)


class SlugAndShortCodeTests(TestCase):
    def test_every_new_article_gets_a_short_code(self):
        article = make_article('has-a-slug', Article.ArticleType.NEWS_COMMENTARY)
        self.assertEqual(len(article.short_code), 5)

    def test_blank_slug_is_generated_from_title_plus_short_code(self):
        article = Article.objects.create(
            title='Tuberculosis Screening Update', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        )
        self.assertTrue(article.slug.startswith('tuberculosis-screening-update-'))
        self.assertTrue(article.slug.endswith(article.short_code))

    def test_explicit_slug_is_not_overridden(self):
        article = make_article('my-custom-slug', Article.ArticleType.NEWS_COMMENTARY)
        self.assertEqual(article.slug, 'my-custom-slug')

    def test_two_articles_with_identical_titles_get_distinct_slugs(self):
        first = Article.objects.create(
            title='Duplicate Title', abstract='a', article_type=Article.ArticleType.NEWS_COMMENTARY,
            status=Article.Status.PUBLISHED,
        )
        second = Article.objects.create(
            title='Duplicate Title', abstract='b', article_type=Article.ArticleType.NEWS_COMMENTARY,
            status=Article.Status.PUBLISHED,
        )
        self.assertNotEqual(first.slug, second.slug)
        self.assertNotEqual(first.short_code, second.short_code)

    def test_editing_an_existing_article_does_not_change_its_short_code(self):
        article = make_article('stable-code-article', Article.ArticleType.NEWS_COMMENTARY)
        original_code = article.short_code
        article.title = 'Updated Title'
        article.save()
        self.assertEqual(article.short_code, original_code)

    def test_short_link_redirects_to_canonical_detail_page(self):
        article = make_article('short-link-target', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_short_link', args=[article.short_code]))
        self.assertRedirects(
            response, reverse('articles:article_detail', args=[article.slug]), status_code=301,
        )

    def test_short_link_404s_for_unpublished_article(self):
        article = make_article('draft-short-link', Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT)
        response = self.client.get(reverse('articles:article_short_link', args=[article.short_code]))
        self.assertEqual(response.status_code, 404)

    def test_short_link_404s_for_unknown_code(self):
        response = self.client.get(reverse('articles:article_short_link', args=['zzzzz']))
        self.assertEqual(response.status_code, 404)

    def test_article_detail_page_exposes_short_url(self):
        article = make_article('exposed-short-url', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, f'/articles/{article.short_code}/')

    def test_a_short_code_shaped_manual_slug_still_takes_the_slug_route(self):
        # An editor-typed slug that happens to be 5 lowercase-alnum chars
        # (the same shape as a short_code) must still resolve as a normal
        # article — it's a real slug value, distinct from any article's
        # actual short_code, so it should never hit article_short_link.
        article = make_article('abcde', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertEqual(response.status_code, 200)

    def test_create_form_generates_slug_when_left_blank(self):
        from users.models import User

        editor = User.objects.create_user(
            email='slug-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(editor)
        response = self.client.post(reverse('articles:manage_article_create'), {
            'title': 'Freshly Typed Headline', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'abstract': 'An abstract.', 'action': 'draft',
        })
        article = Article.objects.get(title='Freshly Typed Headline')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(article.slug.startswith('freshly-typed-headline-'))
        self.assertEqual(len(article.short_code), 5)


class CitationLinkifyingTests(TestCase):
    """articles.citations.linkify_citations — turns editor-typed [N]
    placeholders into hyperlinked superscripts, at render time only.
    """

    def test_single_placeholder_is_linkified(self):
        result = linkify_citations('<p>Some claim.[1]</p>')
        self.assertEqual(result, '<p>Some claim.<sup><a href="#ref-1">1</a></sup></p>')

    def test_multiple_placeholders_including_multi_digit(self):
        result = linkify_citations('Look [1] and [2] and [10].')
        self.assertEqual(
            result,
            'Look <sup><a href="#ref-1">1</a></sup> and <sup><a href="#ref-2">2</a></sup> '
            'and <sup><a href="#ref-10">10</a></sup>.',
        )

    def test_adjacent_placeholders(self):
        result = linkify_citations('Combined risk.[6][7]')
        self.assertEqual(
            result, 'Combined risk.<sup><a href="#ref-6">6</a></sup><sup><a href="#ref-7">7</a></sup>',
        )

    def test_empty_content_returned_unchanged(self):
        self.assertEqual(linkify_citations(''), '')
        self.assertIsNone(linkify_citations(None))

    def test_content_with_no_placeholders_is_unchanged(self):
        html = '<p>Nothing to cite here.</p>'
        self.assertEqual(linkify_citations(html), html)


class ArticleDetailCitationRenderingTests(TestCase):
    """End-to-end: [N] placeholders in html_content render as working
    #ref-N links against the auto-generated references list anchors, and a
    bare URL inside a reference entry gets auto-linked via |urlize.
    """

    def test_placeholder_becomes_working_anchor_link(self):
        article = make_article('citation-article', Article.ArticleType.NEWS_COMMENTARY)
        article.html_content = '<p>A claim needing support.[1]</p>'
        article.references = 'Smith J. Some Journal. 2024.'
        article.save()

        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, '<sup><a href="#ref-1">1</a></sup>')
        self.assertContains(response, 'id="ref-1"')
        self.assertNotContains(response, '[1]')

    def test_bare_url_in_reference_entry_is_urlized(self):
        article = make_article('citation-url-article', Article.ArticleType.NEWS_COMMENTARY)
        article.html_content = '<p>See the source.[1]</p>'
        article.references = 'Thapa B. Ajna Health Lens. 2025. https://doi.org/10.1234/ahl.2025.010329'
        article.save()

        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(
            response, '<a href="https://doi.org/10.1234/ahl.2025.010329" rel="nofollow">',
        )

    def test_stored_html_content_is_never_mutated_by_rendering(self):
        article = make_article('citation-source-untouched', Article.ArticleType.NEWS_COMMENTARY)
        article.html_content = '<p>A claim.[1]</p>'
        article.references = 'Smith J. Some Journal. 2024.'
        article.save()

        self.client.get(reverse('articles:article_detail', args=[article.slug]))
        article.refresh_from_db()
        self.assertEqual(article.html_content, '<p>A claim.[1]</p>')


class CKEditorWidgetRenderingTests(TestCase):
    """Article.html_content and NewsletterIssue.body_html swapped from plain
    <textarea>s to django-ckeditor-5's widget (see articles/forms.py,
    newsletter/forms.py) — these confirm the manage forms actually render
    the widget's markup/assets, not just that the field is still present.
    """

    def setUp(self):
        from users.models import User

        self.editor = User.objects.create_user(
            email='ckeditor-editor@example.com', password='pw', first_name='E', last_name='D',
            role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def test_article_create_form_renders_ckeditor_widget(self):
        response = self.client.get(reverse('articles:manage_article_create'))
        self.assertContains(response, 'ck-editor-container')
        self.assertContains(response, 'django_ckeditor_5/dist/bundle.js')

    def test_article_form_widget_config_has_source_editing(self):
        from .forms import ArticleForm

        widget = ArticleForm().fields['html_content'].widget
        self.assertIn('sourceEditing', widget.config['toolbar'])

    def test_newsletter_compose_form_renders_ckeditor_widget(self):
        response = self.client.get(reverse('newsletter:manage_issue_compose'))
        self.assertContains(response, 'ck-editor-container')
        self.assertContains(response, 'django_ckeditor_5/dist/bundle.js')


class CKEditorUploadPermissionTests(TestCase):
    """The upload endpoint is registered under a custom wrapper view
    (ajna_health_lens/ckeditor_views.py) instead of the package's own urls.py,
    so it's gated by this project's EDITORIAL_ROLES instead of the package's
    built-in "staff"/"authenticated" modes — neither of which fits, since
    Editor/EiC accounts here don't carry is_staff=True (see
    ajna_health_lens/settings.py's CKEDITOR_5_FILE_UPLOAD_PERMISSION comment).
    """

    def _make_image_upload(self):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buffer = io.BytesIO()
        Image.new('RGB', (10, 10)).save(buffer, format='JPEG')
        return SimpleUploadedFile('test.jpg', buffer.getvalue(), content_type='image/jpeg')

    def test_anonymous_upload_redirects_to_login(self):
        response = self.client.post(reverse('ck_editor_5_upload_file'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_non_editorial_user_gets_403(self):
        from users.models import User

        reader = User.objects.create_user(
            email='ckeditor-reader@example.com', password='pw', first_name='R', last_name='D',
            role=User.Role.VERIFIED_AUTHOR,
        )
        self.client.force_login(reader)
        response = self.client.post(reverse('ck_editor_5_upload_file'), {'upload': self._make_image_upload()})
        self.assertEqual(response.status_code, 403)

    def test_editorial_user_can_upload(self):
        from users.models import User

        editor = User.objects.create_user(
            email='ckeditor-uploader@example.com', password='pw', first_name='E', last_name='D',
            role=User.Role.EDITOR,
        )
        self.client.force_login(editor)
        response = self.client.post(reverse('ck_editor_5_upload_file'), {'upload': self._make_image_upload()})
        self.assertEqual(response.status_code, 200)
        self.assertIn('url', response.json())


def _comment_post_data(article, comment_text, **extra):
    """Builds valid POST data for django_comments's post_comment view —
    including the anti-spoofing content_type/object_pk/timestamp/security_hash
    fields, which only django_comments_xtd's own form knows how to generate.
    """
    from django_comments_xtd.forms import XtdCommentForm

    data = XtdCommentForm(article).initial.copy()
    data.update({
        'comment': comment_text, 'name': '', 'email': '', 'url': '',
        'reply_to': 0, 'followup': False, 'honeypot': '',
        'next': article.get_absolute_url(),
    })
    data.update(extra)
    return data


class ArticleCommentsTests(TestCase):
    """Reader comments (django-comments-xtd) — see ARCHITECTURE.md's
    comments section. Authenticated readers post immediately; anonymous
    readers must confirm via an emailed link first (the package's own
    anti-spam mechanism, no CAPTCHA). Threaded up to 3 levels deep.
    """

    def setUp(self):
        from users.models import User

        self.article = make_article('commentable-article', Article.ArticleType.NEWS_COMMENTARY)
        self.reader = User.objects.create_user(
            email='commenter@example.com', password='pw', first_name='Reader', last_name='One',
        )

    def test_get_absolute_url(self):
        self.assertEqual(
            self.article.get_absolute_url(), reverse('articles:article_detail', args=[self.article.slug]),
        )

    def test_comment_form_and_count_render_on_article_detail(self):
        response = self.client.get(self.article.get_absolute_url())
        self.assertContains(response, 'id_comment')
        self.assertContains(response, 'Comments')

    def test_authenticated_user_comment_posts_immediately(self):
        from django_comments_xtd.models import XtdComment

        self.client.force_login(self.reader)
        response = self.client.post(
            reverse('comments-post-comment'),
            _comment_post_data(self.article, 'A signed-in reader comment.'),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        comment = XtdComment.objects.get(comment='A signed-in reader comment.')
        self.assertTrue(comment.is_public)
        self.assertEqual(comment.user, self.reader)
        self.assertContains(response, 'A signed-in reader comment.')

    def test_anonymous_comment_requires_email_confirmation(self):
        from django.core import mail

        from django_comments_xtd.models import XtdComment

        response = self.client.post(
            reverse('comments-post-comment'),
            _comment_post_data(
                self.article, 'An anonymous reader comment.', name='Anon Reader', email='anon@example.com',
            ),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(XtdComment.objects.filter(comment='An anonymous reader comment.').exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['anon@example.com'])
        self.assertIn('confirm', mail.outbox[0].body)

    def test_confirming_anonymous_comment_publishes_it(self):
        import re

        from django.core import mail

        from django_comments_xtd.models import XtdComment

        self.client.post(
            reverse('comments-post-comment'),
            _comment_post_data(
                self.article, 'Confirm-me comment.', name='Anon Reader', email='anon2@example.com',
            ),
        )
        confirm_path = re.search(r'(/comments/confirm/\S+/)', mail.outbox[0].body).group(1)
        response = self.client.get(confirm_path, follow=True)
        self.assertEqual(response.status_code, 200)
        comment = XtdComment.objects.get(comment='Confirm-me comment.')
        self.assertTrue(comment.is_public)
        self.assertEqual(comment.user_email, 'anon2@example.com')
        self.assertContains(response, 'Confirm-me comment.')

    def test_threaded_reply_nests_under_parent(self):
        from django_comments_xtd.models import XtdComment

        self.client.force_login(self.reader)
        self.client.post(
            reverse('comments-post-comment'), _comment_post_data(self.article, 'Parent comment.'),
        )
        parent = XtdComment.objects.get(comment='Parent comment.')

        self.client.post(
            reverse('comments-post-comment'),
            _comment_post_data(self.article, 'Reply comment.', reply_to=parent.pk),
        )
        reply = XtdComment.objects.get(comment='Reply comment.')
        self.assertEqual(reply.level, 1)
        self.assertEqual(reply.parent_id, parent.pk)
        self.assertEqual(reply.thread_id, parent.thread_id)

    def test_comments_hidden_in_preview_mode(self):
        from users.models import User

        editor = User.objects.create_user(
            email='preview-editor@example.com', password='pw', first_name='E', last_name='D',
            role=User.Role.EDITOR,
        )
        self.client.force_login(editor)
        response = self.client.post(reverse('articles:manage_article_preview'), {
            'title': 'Preview Article', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'abstract': 'An abstract.',
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id_comment')

    def test_honeypot_rejects_spam_submission(self):
        from django_comments_xtd.models import XtdComment

        self.client.force_login(self.reader)
        self.client.post(
            reverse('comments-post-comment'),
            _comment_post_data(self.article, 'Spam comment.', honeypot='filled-in-by-a-bot'),
        )
        self.assertFalse(XtdComment.objects.filter(comment='Spam comment.').exists())
