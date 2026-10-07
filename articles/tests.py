import datetime
import json

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from billing.models import ArticleGift, SubscriptionPlan, UserSubscription
from sections.models import Section, SectionFollow

from .citations import linkify_citations
from .content_ads import build_content_blocks
from .forms import ArticleForm, TagifyKeywordsField
from .models import Article, ArticleAuthor, Author, Bookmark, Keyword, KeywordEvent, KeywordFollow
from .toc import extract_toc


def make_article(slug, article_type, status=Article.Status.PUBLISHED, homepage_section='', publication_date=None):
    return Article.objects.create(
        title=slug.replace('-', ' ').title(), slug=slug, abstract='Abstract',
        article_type=article_type, status=status, homepage_section=homepage_section,
        publication_date=publication_date,
    )


def grant_publish(user):
    """Give an Editor the "Can publish" permission (EiC/Admin have it implicitly)."""
    from django.contrib.auth.models import Permission

    user.user_permissions.add(Permission.objects.get(codename='publish_article', content_type__app_label='articles'))
    # Drop Django's cached permission set so has_perm sees the new grant.
    for attr in ('_perm_cache', '_user_perm_cache'):
        if hasattr(user, attr):
            delattr(user, attr)
    return user


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

    def test_structured_data_marks_open_access_article_as_free(self):
        article = make_article('open-access-structured-data', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, '"isAccessibleForFree": true')
        # "News & Commentary" — the "&" survives ld_json's escaping as the
        # unicode-escaped &, not a literal ampersand.
        self.assertContains(response, '"articleSection": "News \\u0026 Commentary"')

    def test_structured_data_marks_subscription_article_as_not_free(self):
        article = make_article('subscription-structured-data', Article.ArticleType.NEWS_COMMENTARY)
        article.access_type = Article.AccessType.SUBSCRIPTION
        article.save()
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, '"isAccessibleForFree": false')

    def test_structured_data_includes_keywords(self):
        article = make_article('keyword-structured-data', Article.ArticleType.NEWS_COMMENTARY)
        article.keyword_tags.set([
            Keyword.objects.create(name='Diabetes'), Keyword.objects.create(name='Public Health'),
        ])
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, '"keywords": "Diabetes, Public Health"')

    def test_structured_data_omits_keywords_key_when_none_set(self):
        article = make_article('no-keyword-structured-data', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertNotContains(response, '"keywords"')

    def test_home_page_has_a_specific_title_and_description(self):
        response = self.client.get(reverse('articles:home'))
        content = response.content.decode()
        self.assertIn('<title>', content)
        self.assertNotIn('<title></title>', content)
        self.assertIn('name="description"', content)

    def test_article_list_title_reflects_type_filter(self):
        response = self.client.get(reverse('articles:article_list'), {'type': Article.ArticleType.NEWS_COMMENTARY})
        self.assertContains(response, '<title>News &amp; Commentary')

    def test_article_list_title_reflects_no_filter(self):
        response = self.client.get(reverse('articles:article_list'))
        self.assertContains(response, '<title>All Articles')

    def test_search_results_page_has_query_in_title_and_is_noindex(self):
        response = self.client.get(reverse('articles:search'), {'q': 'diabetes'})
        content = response.content.decode()
        self.assertIn('<title>Search results for &quot;diabetes&quot;', content)
        self.assertIn('name="robots" content="noindex, follow"', content)

    def test_search_page_with_no_query_is_still_noindex(self):
        response = self.client.get(reverse('articles:search'))
        self.assertContains(response, 'name="robots" content="noindex, follow"')

    def test_non_search_page_defaults_to_indexable(self):
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'name="robots" content="index, follow"')

    def test_every_page_has_sitewide_organization_and_website_structured_data(self):
        article = make_article('sitewide-schema-article', Article.ArticleType.NEWS_COMMENTARY)
        for url in [reverse('articles:home'), reverse('articles:article_detail', args=[article.slug])]:
            response = self.client.get(url)
            self.assertContains(response, '"@type": "NewsMediaOrganization"')
            self.assertContains(response, '"@type": "WebSite"')
            self.assertContains(response, '"@type": "SearchAction"')

    def test_article_page_has_breadcrumb_structured_data(self):
        article = make_article('breadcrumb-article', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, '"@type": "BreadcrumbList"')
        self.assertContains(response, article.title)

    def test_author_page_has_person_structured_data(self):
        from articles.models import ArticleAuthor
        from users.models import User

        author = User.objects.create_user(
            email='schema-author@example.com', password='pw', first_name='Ada', last_name='Lovelace',
            role=User.Role.VERIFIED_AUTHOR, affiliation='Analytical Engines Inc.', bio='Writes about computing.',
        )
        article = make_article('author-schema-article', Article.ArticleType.NEWS_COMMENTARY)
        # Author profile left blank on purpose — the page falls back to the
        # linked account's own profile (affiliation, bio) — see Author.display_*.
        profile = Author.for_user(author)
        ArticleAuthor.objects.create(article=article, author=profile, order=0, is_corresponding=True)

        response = self.client.get(reverse('articles:author_detail', args=[profile.slug]))
        content = response.content.decode()
        self.assertIn('<title>Ada Lovelace', content)
        self.assertIn('Writes about computing.', content)
        self.assertIn('"@type": "Person"', content)
        self.assertIn('"name": "Ada Lovelace"', content)
        self.assertIn('"Analytical Engines Inc."', content)

    def test_author_page_person_schema_omits_sameas_when_no_profiles_set(self):
        from articles.models import ArticleAuthor
        from users.models import User

        author = User.objects.create_user(
            email='schema-author2@example.com', password='pw', first_name='Bare', last_name='Profile',
            role=User.Role.VERIFIED_AUTHOR,
        )
        article = make_article('author-schema-article2', Article.ArticleType.NEWS_COMMENTARY)
        profile = Author.for_user(author)
        ArticleAuthor.objects.create(article=article, author=profile, order=0, is_corresponding=True)

        response = self.client.get(reverse('articles:author_detail', args=[profile.slug]))
        self.assertNotContains(response, '"sameAs"')

    def test_non_article_page_falls_back_to_sitewide_defaults(self):
        response = self.client.get(reverse('articles:home'))
        content = response.content.decode()
        self.assertIn('property="og:type" content="website"', content)

    def test_canonical_url_strips_querystring_on_a_page_with_no_explicit_canonical(self):
        # Regression guard — the old fallback (request.build_absolute_uri
        # with no args) self-canonicalized every filtered/paginated variant
        # of a list page as its own indexable URL.
        make_article('canonical-filter-article', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_list'), {'type': Article.ArticleType.NEWS_COMMENTARY})
        content = response.content.decode()
        self.assertIn(f'rel="canonical" href="http://testserver{reverse("articles:article_list")}"', content)
        self.assertNotIn('?type=', content.split('rel="canonical"')[1][:200])

    def test_article_detail_canonical_url_is_unaffected(self):
        article = make_article('canonical-detail-article', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        content = response.content.decode()
        expected = f'http://testserver{reverse("articles:article_detail", args=[article.slug])}'
        self.assertIn(f'rel="canonical" href="{expected}"', content)


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

    def test_robots_txt_also_points_to_news_sitemap(self):
        response = self.client.get(reverse('robots_txt'))
        self.assertContains(response, '/news-sitemap.xml')


class NewsSitemapTests(TestCase):
    def test_recent_published_article_is_included(self):
        article = make_article(
            'news-sitemap-recent', Article.ArticleType.NEWS_COMMENTARY, publication_date=timezone.localdate(),
        )
        response = self.client.get(reverse('news_sitemap'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(article.title, content)
        self.assertIn('<news:news>', content)
        self.assertIn('<news:name>Ajna Health Lens</news:name>', content)
        self.assertIn('<news:language>en</news:language>', content)
        # Full W3C timestamp (published_at), not just the day.
        self.assertIn(f'<news:publication_date>{timezone.localtime(article.published_at).isoformat()}</news:publication_date>', content)

    def test_article_older_than_two_days_is_excluded(self):
        old_article = make_article(
            'news-sitemap-old', Article.ArticleType.NEWS_COMMENTARY,
            publication_date=timezone.localdate() - datetime.timedelta(days=5),
        )
        response = self.client.get(reverse('news_sitemap'))
        self.assertNotIn(old_article.title, response.content.decode())

    def test_draft_article_is_excluded_even_if_recent(self):
        draft = make_article(
            'news-sitemap-draft', Article.ArticleType.NEWS_COMMENTARY,
            status=Article.Status.DRAFT, publication_date=timezone.localdate(),
        )
        response = self.client.get(reverse('news_sitemap'))
        self.assertNotIn(draft.title, response.content.decode())

    def test_content_type_is_xml(self):
        response = self.client.get(reverse('news_sitemap'))
        self.assertIn('xml', response['Content-Type'])


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

        # pay_per_article, not subscription — subscription-tier downloads
        # are now covered by the metered free-sample allowance (see
        # billing/tests.py:MeteredPaywallViewTests), so a fresh anonymous
        # reader's first request there succeeds rather than 404ing.
        # pay_per_article stays a hard, unmetered paywall, which is what
        # this test actually means to exercise: a genuinely blocked
        # download must not increment download_count as a side effect.
        article = make_article('gated-downloadable', Article.ArticleType.ORIGINAL_RESEARCH)
        article.access_type = Article.AccessType.PAY_PER_ARTICLE
        article.price = 2
        article.pdf_file = SimpleUploadedFile('test.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        article.save()

        response = self.client.get(reverse('articles:article_download', args=[article.slug]))
        self.assertEqual(response.status_code, 404)
        article.refresh_from_db()
        self.assertEqual(article.download_count, 0)


def make_keyword(name):
    return Keyword.objects.create(name=name, slug=slugify(name))


class KeywordBrowsingTests(TestCase):
    """August 2026: Article.keywords (flat comma-separated CharField) was
    replaced by Keyword + Article.keyword_tags (a real M2M) — see Keyword's
    docstring in articles/models.py. ?keyword=<slug> is now an exact match,
    not an icontains substring match against a joined string.
    """

    def test_keyword_pill_links_to_topic_page(self):
        article = Article.objects.create(
            title='Tagged Article', slug='tagged-article', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        )
        article.keyword_tags.set([make_keyword('Tuberculosis'), make_keyword('Screening')])
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, reverse('articles:topic_detail', args=['tuberculosis']))
        self.assertContains(response, 'topic-pill__name">Tuberculosis<')

    def test_article_list_filters_by_keyword(self):
        tb_keyword = make_keyword('Tuberculosis')
        matching = Article.objects.create(
            title='TB Article', slug='tb-article', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        )
        matching.keyword_tags.set([tb_keyword, make_keyword('Screening')])
        other = Article.objects.create(
            title='Unrelated Article', slug='unrelated-article', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        )
        other.keyword_tags.set([make_keyword('Maternal Health')])
        response = self.client.get(reverse('articles:article_list'), {'keyword': tb_keyword.slug})
        articles = list(response.context['articles'])
        self.assertIn(matching, articles)
        self.assertNotIn(other, articles)
        self.assertEqual(response.context['selected_keyword'], 'tuberculosis')
        self.assertEqual(response.context['selected_keyword_label'], 'Tuberculosis')

    def test_keyword_search_box_prefills_current_keyword(self):
        make_keyword('Tuberculosis')
        response = self.client.get(reverse('articles:article_list'), {'keyword': 'tuberculosis'})
        self.assertContains(response, '&quot;value&quot;: &quot;Tuberculosis&quot;')
        self.assertContains(response, '&quot;slug&quot;: &quot;tuberculosis&quot;')

    def test_type_pill_preserves_active_keyword_filter(self):
        make_keyword('Tuberculosis')
        response = self.client.get(reverse('articles:article_list'), {'keyword': 'tuberculosis'})
        self.assertContains(response, '&keyword=tuberculosis')

    def test_unknown_keyword_slug_returns_no_results_without_error(self):
        Article.objects.create(
            title='Some Article', slug='some-article', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        )
        response = self.client.get(reverse('articles:article_list'), {'keyword': 'does-not-exist'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['articles']), [])
        self.assertEqual(response.context['selected_keyword_label'], '')


class KeywordModelTests(TestCase):
    def test_slug_auto_generated_from_name(self):
        keyword = Keyword.objects.create(name='Maternal Health')
        self.assertEqual(keyword.slug, 'maternal-health')

    def test_explicit_slug_is_not_overwritten(self):
        keyword = Keyword.objects.create(name='Maternal Health', slug='custom-slug')
        self.assertEqual(keyword.slug, 'custom-slug')

    def test_name_is_unique(self):
        Keyword.objects.create(name='Diabetes')
        with self.assertRaises(IntegrityError):
            Keyword.objects.create(name='Diabetes')


class TagifyKeywordsFieldTests(TestCase):
    def test_parses_tagify_json_format(self):
        field = TagifyKeywordsField()
        keywords = field.clean('[{"value": "Diabetes"}, {"value": "Cardiology"}]')
        self.assertEqual([k.name for k in keywords], ['Diabetes', 'Cardiology'])
        self.assertEqual(Keyword.objects.count(), 2)

    def test_falls_back_to_comma_split_for_non_json_input(self):
        field = TagifyKeywordsField()
        keywords = field.clean('Diabetes, Cardiology')
        self.assertEqual([k.name for k in keywords], ['Diabetes', 'Cardiology'])

    def test_reuses_existing_keyword_by_slug_not_by_exact_casing(self):
        existing = make_keyword('diabetes')
        field = TagifyKeywordsField()
        keywords = field.clean('[{"value": "Diabetes"}]')
        self.assertEqual(keywords, [existing])
        self.assertEqual(Keyword.objects.count(), 1)

    def test_duplicate_tags_in_one_submission_are_deduped(self):
        field = TagifyKeywordsField()
        keywords = field.clean('[{"value": "Diabetes"}, {"value": "diabetes"}]')
        self.assertEqual(len(keywords), 1)

    def test_empty_value(self):
        field = TagifyKeywordsField(required=False)
        self.assertEqual(field.clean(''), [])


class ArticleFormKeywordsTests(TestCase):
    def _valid_data(self, **overrides):
        data = {
            'title': 'A New Article', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'abstract': 'An abstract.',
        }
        data.update(overrides)
        return data

    def test_save_creates_keyword_rows_and_links_them(self):
        form = ArticleForm(data=self._valid_data(keywords='[{"value": "Diabetes"}, {"value": "Cardiology"}]'))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save()
        self.assertEqual(sorted(k.name for k in article.keyword_tags.all()), ['Cardiology', 'Diabetes'])

    def test_commit_false_defers_keywords_until_save_m2m(self):
        form = ArticleForm(data=self._valid_data(keywords='[{"value": "Diabetes"}]'))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save(commit=False)
        article.save()
        self.assertEqual(article.keyword_tags.count(), 0)
        form.save_m2m()
        self.assertEqual(article.keyword_tags.count(), 1)

    def test_editing_replaces_keyword_set(self):
        article = Article.objects.create(
            title='Existing', slug='existing-article', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT,
        )
        article.keyword_tags.set([make_keyword('Old Tag')])
        form = ArticleForm(
            data=self._valid_data(keywords='[{"value": "New Tag"}]'), instance=article,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual([k.name for k in article.keyword_tags.all()], ['New Tag'])

    def test_edit_form_prefills_existing_keywords_as_tagify_json(self):
        article = Article.objects.create(
            title='Existing', slug='existing-article-2', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT,
        )
        article.keyword_tags.set([make_keyword('Existing Tag')])
        form = ArticleForm(instance=article)
        self.assertIn('"value": "Existing Tag"', form.fields['keywords'].initial)


class ArticleFormSectionFieldTests(TestCase):
    def _valid_data(self, **overrides):
        data = {
            'title': 'A New Article', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'abstract': 'An abstract.',
        }
        data.update(overrides)
        return data

    def test_section_is_optional(self):
        form = ArticleForm(data=self._valid_data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_can_save_with_a_leaf_section(self):
        from sections.models import Section

        top = Section.objects.create(name_en='Test Top', slug='form-test-top')
        child = Section.objects.create(name_en='Test Child', slug='form-test-child', parent=top)
        form = ArticleForm(data=self._valid_data(section=child.pk))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save()
        self.assertEqual(article.section, child)

    def test_can_save_with_a_top_level_section(self):
        from sections.models import Section

        top = Section.objects.create(name_en='Test Top', slug='form-test-top2')
        form = ArticleForm(data=self._valid_data(section=top.pk))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save()
        self.assertEqual(article.section, top)

    def test_link_override_sections_are_excluded_from_choices(self):
        from sections.models import Section

        Section.objects.create(name_en='Test Training', slug='form-test-training', link_url_name='training:course_list')
        form = ArticleForm()
        flat_choice_values = []
        for group_or_choice in form.fields['section'].choices:
            key, value = group_or_choice
            if isinstance(value, list):
                flat_choice_values.extend(v for v, _label in value)
            else:
                flat_choice_values.append(key)
        section = Section.objects.get(slug='form-test-training')
        self.assertNotIn(section.pk, flat_choice_values)


class ArticleFormSanitizationTests(TestCase):
    """html_content is sanitized on save (articles/sanitize.py) — defense
    in depth on top of the EDITORIAL_ROLES-only write access this field
    already relies on. <script> stays allowed (D3.js chart embeds, see
    ROADMAP.md's WYSIWYG section), but only inline or from the one CDN this
    project preloads.
    """

    def _valid_data(self, **overrides):
        data = {
            'title': 'A New Article', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'abstract': 'An abstract.',
        }
        data.update(overrides)
        return data

    def test_script_with_onerror_style_attribute_is_stripped(self):
        form = ArticleForm(data=self._valid_data(html_content='<img src="x" onerror="alert(1)">'))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save()
        self.assertNotIn('onerror', article.html_content)

    def test_script_from_untrusted_src_is_stripped_to_empty(self):
        form = ArticleForm(data=self._valid_data(html_content='<script src="https://evil.example/x.js"></script>'))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save()
        self.assertNotIn('evil.example', article.html_content)

    def test_inline_script_for_d3_embed_is_preserved(self):
        html = '<div id="chart"></div><script>d3.select("#chart").append("svg");</script>'
        form = ArticleForm(data=self._valid_data(html_content=html))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save()
        self.assertIn('<script>d3.select', article.html_content)

    def test_trusted_cdn_script_src_is_preserved(self):
        html = '<script src="https://d3js.org/d3.v7.min.js"></script>'
        form = ArticleForm(data=self._valid_data(html_content=html))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save()
        self.assertIn('https://d3js.org/d3.v7.min.js', article.html_content)

    def _clean(self, html):
        form = ArticleForm(data=self._valid_data(html_content=html))
        self.assertTrue(form.is_valid(), form.errors)
        return form.save().html_content

    def test_alignment_including_justify_is_kept_but_other_styles_are_not(self):
        self.assertEqual(self._clean('<p style="text-align:justify;">x</p>'), '<p style="text-align:justify;">x</p>')
        cleaned = self._clean('<p style="position:fixed;top:0;background:url(javascript:alert(1));text-align:center">x</p>')
        self.assertEqual(cleaned, '<p style="text-align:center;">x</p>')

    def test_uploaded_image_with_caption_alignment_and_size_is_kept(self):
        html = ('<figure class="image image-style-align-left image_resized" style="width:50%;">'
                '<img src="/media/django_ckeditor_5/x.png" alt="Clinic"><figcaption>A clinic.</figcaption></figure>')
        self.assertEqual(self._clean(html), html)

    def test_video_embed_kept_only_from_trusted_players(self):
        cleaned = self._clean(
            '<figure class="media"><div data-oembed-url="https://youtu.be/abc"><div style="position:relative;">'
            '<iframe src="https://www.youtube.com/embed/abc" style="position:absolute;width:100%;" allowfullscreen="">'
            '</iframe></div></div></figure>'
        )
        self.assertIn('src="https://www.youtube.com/embed/abc"', cleaned)
        self.assertIn('referrerpolicy="strict-origin-when-cross-origin"', self._clean(
            '<iframe src="https://www.youtube.com/embed/abc" referrerpolicy="strict-origin-when-cross-origin"></iframe>'))
        self.assertNotIn('unsafe-url', self._clean('<iframe src="https://www.youtube.com/embed/abc" referrerpolicy="unsafe-url"></iframe>'))
        self.assertNotIn('position', cleaned)
        self.assertNotIn('evil', self._clean('<iframe src="https://evil.example/embed/x"></iframe>'))

    def test_list_numbering_style_is_kept(self):
        html = '<ol style="list-style-type:lower-roman;" start="3"><li>x</li></ol>'
        self.assertEqual(self._clean(html), html)

    def test_normal_rich_content_is_preserved(self):
        html = '<h2>Title</h2><p>Some <strong>bold</strong> text.</p>'
        form = ArticleForm(data=self._valid_data(html_content=html))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save()
        self.assertEqual(article.html_content, html)


class KeywordAutocompleteTests(TestCase):
    def test_returns_matching_keywords(self):
        make_keyword('Diabetes')
        make_keyword('Cardiology')
        response = self.client.get(reverse('articles:keyword_autocomplete'), {'q': 'diab'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['value'], 'Diabetes')
        self.assertEqual(data[0]['slug'], 'diabetes')

    def test_empty_query_returns_a_sample_of_keywords(self):
        make_keyword('Diabetes')
        make_keyword('Cardiology')
        response = self.client.get(reverse('articles:keyword_autocomplete'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_never_creates_a_keyword(self):
        response = self.client.get(reverse('articles:keyword_autocomplete'), {'q': 'nonexistent-topic'})
        self.assertEqual(response.json(), [])
        self.assertEqual(Keyword.objects.count(), 0)


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

    def test_result_count_label_matches_actual_result_count(self):
        # Regression test: `{{ page_obj.paginator.count|default:articles|length }}`
        # chains left-to-right — default only substitutes on a falsy value, so a
        # real (nonzero) count just passes through unchanged as an int, and
        # |length on an int raises TypeError internally and silently returns 0.
        # The label showed "0 RESULT(S)" for every non-empty search.
        Article.objects.create(
            title='Rare Disease Registry Update', slug='rare-disease-registry', abstract='A rare disease topic.',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        )
        response = self.client.get(reverse('articles:search'), {'q': 'rare'})
        # Label is now properly pluralized ("1 RESULT" / "2 RESULTS") via
        # {% blocktrans count %}, so it can be translated (Nepali UI).
        self.assertContains(response, '1 RESULT FOR')
        self.assertNotContains(response, '0 RESULT')

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


class KeywordEventTrackingTests(TestCase):
    """Keyword-pill impressions (recorded with a counted article view) and
    clicks (articles:keyword_click, sent by sendBeacon) — the data behind
    the editorial Keyword Analytics page.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.article = make_article('keyword-tracked-article', Article.ArticleType.NEWS_COMMENTARY)
        self.tb = make_keyword('Tuberculosis')
        self.screening = make_keyword('Screening')
        self.article.keyword_tags.set([self.tb, self.screening])

    def _click(self, keyword=None, placement='header'):
        return self.client.post(
            reverse('articles:keyword_click', args=[(keyword or self.tb).pk]),
            {'article': self.article.pk, 'placement': placement},
        )

    def _count(self, event_type):
        return KeywordEvent.objects.filter(event_type=event_type).count()

    def test_article_view_records_one_impression_per_keyword(self):
        self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        impressions = KeywordEvent.objects.filter(event_type=KeywordEvent.EventType.IMPRESSION)
        self.assertEqual(set(impressions.values_list('keyword', flat=True)), {self.tb.pk, self.screening.pk})
        self.assertTrue(all(e.article_id == self.article.pk for e in impressions))

    def test_refresh_does_not_add_impressions(self):
        for _ in range(3):
            self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertEqual(self._count(KeywordEvent.EventType.IMPRESSION), 2)

    def test_pills_carry_click_tracking_attributes(self):
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertContains(response, reverse('articles:keyword_click', args=[self.tb.pk]), count=2)
        self.assertContains(response, 'data-placement="header"')
        self.assertContains(response, 'data-placement="footer"')

    def test_click_is_recorded_with_article_and_placement(self):
        response = self._click(placement='footer')
        self.assertEqual(response.status_code, 204)
        event = KeywordEvent.objects.get(event_type=KeywordEvent.EventType.CLICK)
        self.assertEqual((event.keyword, event.article, event.placement), (self.tb, self.article, 'footer'))

    def test_repeat_click_in_same_session_is_deduplicated(self):
        self._click()
        self._click()
        self._click(keyword=self.screening)
        self.assertEqual(self._count(KeywordEvent.EventType.CLICK), 2)

    def test_unknown_placement_is_stored_blank(self):
        self._click(placement='sidebar-hack')
        self.assertEqual(KeywordEvent.objects.get().placement, '')

    def test_editorial_staff_clicks_are_not_recorded(self):
        from users.models import User

        editor = User.objects.create_user(
            email='kw-click-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(editor)
        self.assertEqual(self._click().status_code, 204)
        self.assertEqual(self._count(KeywordEvent.EventType.CLICK), 0)

    def test_click_endpoint_rejects_get(self):
        response = self.client.get(reverse('articles:keyword_click', args=[self.tb.pk]))
        self.assertEqual(response.status_code, 405)


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

    def test_blank_slug_is_generated_from_the_title_without_a_code(self):
        # The short code is the article's second address (/articles/<code>/),
        # not part of the slug (articles/slugs.py).
        article = Article.objects.create(
            title='Tuberculosis Screening Update', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        )
        self.assertEqual(article.slug, 'tuberculosis-screening-update')
        self.assertEqual(len(article.short_code), 5)

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
        self.assertEqual(article.slug, 'freshly-typed-headline')
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

    def test_bracket_index_inside_a_code_block_is_left_alone(self):
        html = '<p>See below.[1]</p><pre><code class="language-python">data[1] = x</code></pre><p>After.[2]</p>'
        result = linkify_citations(html)
        self.assertIn('<pre><code class="language-python">data[1] = x</code></pre>', result)
        self.assertIn('See below.<sup><a href="#ref-1">1</a></sup>', result)
        self.assertIn('After.<sup><a href="#ref-2">2</a></sup>', result)

    def test_bracket_index_inside_inline_code_is_left_alone(self):
        html = '<p>Access with <code>arr[0]</code>, see ref.[1]</p>'
        result = linkify_citations(html)
        self.assertIn('<code>arr[0]</code>', result)
        self.assertIn('<sup><a href="#ref-1">1</a></sup>', result)

    def test_multiple_code_blocks_all_protected(self):
        html = '<pre><code>x[1]</code></pre><p>Text[1]</p><pre><code>y[2]</code></pre>'
        result = linkify_citations(html)
        self.assertIn('<pre><code>x[1]</code></pre>', result)
        self.assertIn('<pre><code>y[2]</code></pre>', result)
        self.assertIn('Text<sup><a href="#ref-1">1</a></sup>', result)


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

        config = ArticleForm().fields['html_content'].widget.config
        for tool in ('sourceEditing', 'alignment', 'insertImage', 'mediaEmbed', 'bulletedList'):
            self.assertIn(tool, config['toolbar']['items'])
        self.assertIn('justify', config['alignment']['options'])
        # Would store Markdown instead of HTML if left on.
        self.assertIn('Markdown', config['removePlugins'])

    def test_editor_config_contains_no_null(self):
        # django-ckeditor-5 parses the config with a JSON reviver that
        # crashes on null, and the whole editor then fails to load.
        import json

        from django.conf import settings

        self.assertNotIn('null', json.dumps(settings.CKEDITOR_5_CONFIGS))

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
        url = response.json()['url']
        # Stored in a dated folder under a random name, not the uploader's filename.
        self.assertRegex(url, r'^/media/articles/inline/\d{4}/\d{2}/[0-9a-f]{16}\.jpg$')
        from django.core.files.storage import default_storage

        default_storage.delete(url.removeprefix('/media/'))

    def test_svg_and_non_images_are_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from users.models import User

        editor = User.objects.create_user(
            email='ckeditor-svg@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(editor)
        svg = SimpleUploadedFile('x.svg', b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', content_type='image/svg+xml')
        self.assertEqual(self.client.post(reverse('ck_editor_5_upload_file'), {'upload': svg}).status_code, 400)
        fake = SimpleUploadedFile('x.png', b'not really an image', content_type='image/png')
        self.assertEqual(self.client.post(reverse('ck_editor_5_upload_file'), {'upload': fake}).status_code, 400)


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

    def test_comment_count_is_per_article(self):
        """"Comments (N)" counts only this article's comments — it used
        get_xtdcomment_count "for articles.article", which is sitewide.
        """
        other = make_article('other-commented-article', Article.ArticleType.NEWS_COMMENTARY)
        self.client.force_login(self.reader)
        for text in ('First on other.', 'Second on other.'):
            self.client.post(reverse('comments-post-comment'), _comment_post_data(other, text))
        self.client.post(reverse('comments-post-comment'), _comment_post_data(self.article, 'Only one here.'))
        response = self.client.get(self.article.get_absolute_url())
        self.assertContains(response, 'Comments (1)')
        self.assertNotContains(response, 'Comments (3)')

    def test_logged_in_post_redirects_to_comments_with_posted_notice(self):
        from django_comments_xtd.models import XtdComment

        self.client.force_login(self.reader)
        response = self.client.post(
            reverse('comments-post-comment'), _comment_post_data(self.article, 'Feedback please.'),
        )
        self.assertRedirects(response, f'{self.article.get_absolute_url()}#comments', fetch_redirect_response=False)
        comment = XtdComment.objects.get(comment='Feedback please.')

        page = self.client.get(self.article.get_absolute_url())
        self.assertContains(page, 'Your comment has been posted.')
        self.assertContains(page, f'href="#c{comment.pk}"')
        # One-shot: gone on the next load.
        self.assertNotContains(self.client.get(self.article.get_absolute_url()), 'Your comment has been posted.')

    def test_anonymous_post_redirects_to_comments_with_check_email_notice(self):
        response = self.client.post(
            reverse('comments-post-comment'),
            _comment_post_data(self.article, 'Pending comment.', name='Anon Reader', email='anon3@example.com'),
        )
        self.assertRedirects(response, f'{self.article.get_absolute_url()}#comments', fetch_redirect_response=False)
        page = self.client.get(self.article.get_absolute_url())
        self.assertContains(page, 'please confirm your email')
        self.assertContains(page, 'anon3@example.com')

    def test_confirmation_link_redirects_to_comments_with_live_notice(self):
        import re

        from django.core import mail

        self.client.post(
            reverse('comments-post-comment'),
            _comment_post_data(self.article, 'Confirm-notice comment.', name='Anon Reader', email='anon5@example.com'),
        )
        self.client.get(self.article.get_absolute_url())  # consume the "check your email" notice
        confirm_path = re.search(r'(/comments/confirm/\S+/)', mail.outbox[0].body).group(1)
        response = self.client.get(confirm_path)
        self.assertRedirects(response, f'{self.article.get_absolute_url()}#comments', fetch_redirect_response=False)
        self.assertContains(self.client.get(self.article.get_absolute_url()), 'your comment is now live')

    def test_notice_only_shows_on_the_commented_article(self):
        other = make_article('notice-other-article', Article.ArticleType.NEWS_COMMENTARY)
        self.client.force_login(self.reader)
        self.client.post(reverse('comments-post-comment'), _comment_post_data(self.article, 'Here only.'))
        self.assertNotContains(self.client.get(other.get_absolute_url()), 'Your comment has been posted.')
        self.assertContains(self.client.get(self.article.get_absolute_url()), 'Your comment has been posted.')

    def test_invalid_post_is_not_redirected(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('comments-post-comment'), _comment_post_data(self.article, ''))
        self.assertEqual(response.status_code, 200)

    def test_confirmed_anonymous_comment_appears_in_editorial_list(self):
        import re

        from django.core import mail

        from users.models import User

        self.client.post(
            reverse('comments-post-comment'),
            _comment_post_data(self.article, 'Moderate-me comment.', name='Anon Reader', email='anon4@example.com'),
        )
        confirm_path = re.search(r'(/comments/confirm/\S+/)', mail.outbox[0].body).group(1)
        self.client.get(confirm_path)

        editor = User.objects.create_user(
            email='comment-list-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(editor)
        response = self.client.get(reverse('admin_custom:manage_comment_list'))
        self.assertContains(response, 'Moderate-me comment.')

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


class CommentRateLimitTests(TestCase):
    """comments-post-comment is overridden in ajna_health_lens/urls.py with
    a rate-limited wrapper (see comments_views.py) — the package's own view
    has no throttle, and email confirmation alone doesn't stop a POST flood
    of unconfirmed rows/confirmation emails.
    """

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.article = make_article('rate-limited-commentable-article', Article.ArticleType.NEWS_COMMENTARY)

    def test_excessive_comment_posts_are_rate_limited(self):
        # Limit is 10/m by IP — the 11th POST in the same window should be
        # blocked rather than processed.
        for i in range(10):
            self.client.post(reverse('comments-post-comment'), _comment_post_data(self.article, f'Comment {i}.'))
        response = self.client.post(reverse('comments-post-comment'), _comment_post_data(self.article, 'Overflow comment.'))
        self.assertEqual(response.status_code, 403)


def _paragraphs(n):
    return ''.join(f'<p>Paragraph {i}.</p>' for i in range(1, n + 1))


class ContentBlockSplittingTests(TestCase):
    """articles.content_ads.build_content_blocks — where in-article ads get
    injected between paragraphs (see article_detail.html). Pure function,
    no DB needed for these.
    """

    def test_empty_content_is_a_single_block_with_no_ad(self):
        self.assertEqual(build_content_blocks(''), [('', None)])
        self.assertEqual(build_content_blocks(None), [(None, None)])

    def test_short_article_gets_no_ad_injected(self):
        html = _paragraphs(3)
        self.assertEqual(build_content_blocks(html), [(html, None)])

    def test_first_ad_appears_after_the_minimum_paragraph_count(self):
        html = _paragraphs(4)
        blocks = build_content_blocks(html)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0][0], _paragraphs(4))
        self.assertEqual(blocks[0][1], 'article_in_content')
        self.assertEqual(blocks[1][1], None)

    def test_zones_alternate_between_rectangle_and_banner(self):
        # MIN=4, then every 5 more: paragraphs 4, 9, 14 -> 3 injection points.
        html = _paragraphs(20)
        blocks = build_content_blocks(html)
        zones = [zone for _chunk, zone in blocks if zone]
        self.assertEqual(zones, ['article_in_content', 'article_content_banner', 'article_in_content'])

    def test_never_more_than_the_maximum_ads(self):
        html = _paragraphs(100)
        blocks = build_content_blocks(html)
        ad_count = sum(1 for _chunk, zone in blocks if zone)
        self.assertEqual(ad_count, 3)

    def test_reassembled_chunks_equal_the_original_content(self):
        html = _paragraphs(20)
        blocks = build_content_blocks(html)
        self.assertEqual(''.join(chunk for chunk, _zone in blocks), html)

    def test_split_only_happens_at_paragraph_boundaries(self):
        html = _paragraphs(20)
        for chunk, _zone in build_content_blocks(html)[:-1]:
            self.assertTrue(chunk.endswith('</p>'))


    def test_ads_never_split_a_blockquote_list_or_table(self):
        nested = '<blockquote><p>q1</p><p>q2</p><p>q3</p><p>q4</p><p>q5</p></blockquote>'
        html = _paragraphs(3) + nested + '<table><tr><td><p>cell</p></td></tr></table>' + _paragraphs(6)
        blocks = build_content_blocks(html)
        self.assertEqual(''.join(chunk for chunk, _zone in blocks), html)
        for chunk, _zone in blocks[:-1]:
            self.assertEqual(chunk.count('<blockquote>'), chunk.count('</blockquote>'))
            self.assertEqual(chunk.count('<table>'), chunk.count('</table>'))
        # 3 top-level paragraphs before the quote, so the first ad comes
        # after the 1st paragraph following it (the 4th top-level one).
        self.assertTrue(blocks[0][0].endswith('</table><p>Paragraph 1.</p>'))


class InArticleAdInjectionRenderingTests(TestCase):
    """End-to-end: a long article's rendered page actually shows in-article
    ads between paragraphs, not just the existing fixed one before the body.
    """

    def _make_ad(self, zone, size, sponsor_name):
        import io

        from django.core.files.base import ContentFile
        from PIL import Image

        from ads.models import AdSlot

        buffer = io.BytesIO()
        Image.new('RGB', size).save(buffer, format='JPEG')
        return AdSlot.objects.create(
            sponsor_name=sponsor_name, zone=zone,
            image=ContentFile(buffer.getvalue(), name=f'{zone}.jpg'), link_url='https://example.com',
        )

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        from ads.models import AdSlot
        self._make_ad(AdSlot.Zone.ARTICLE_IN_CONTENT, (336, 280), 'Rectangle Sponsor')
        self._make_ad(AdSlot.Zone.ARTICLE_CONTENT_BANNER, (728, 90), 'Banner Sponsor')

    def test_short_article_shows_no_in_article_ad(self):
        article = make_article('short-in-article-ad', Article.ArticleType.NEWS_COMMENTARY)
        article.html_content = _paragraphs(3)
        article.save()
        response = self.client.get(article.get_absolute_url())
        content = response.content.decode()
        # The fixed ad before the body (unrelated to injection) still shows,
        # exactly once — a short article just gets no *additional* ones.
        self.assertEqual(content.count('Rectangle Sponsor'), 1)
        self.assertNotIn('Banner Sponsor', content)

    def test_long_article_shows_ads_between_paragraphs(self):
        article = make_article('long-in-article-ad', Article.ArticleType.NEWS_COMMENTARY)
        article.html_content = _paragraphs(20)
        article.save()
        response = self.client.get(article.get_absolute_url())
        content = response.content.decode()
        self.assertIn('Banner Sponsor', content)
        # "Rectangle Sponsor" appears twice on this page: the fixed ad
        # before the body, then again as the first in-article injection
        # (alternation starts with the rectangle zone) — the second
        # occurrence is the one that has to land between paragraphs 4 and 5.
        first_rectangle_ad = content.index('Rectangle Sponsor')
        second_rectangle_ad = content.index('Rectangle Sponsor', first_rectangle_ad + 1)
        self.assertLess(content.index('Paragraph 4.'), second_rectangle_ad)
        self.assertLess(second_rectangle_ad, content.index('Paragraph 5.'))
        # Second injection point (banner, after paragraph 9) lands correctly too.
        self.assertLess(content.index('Paragraph 9.'), content.index('Banner Sponsor'))
        self.assertLess(content.index('Banner Sponsor'), content.index('Paragraph 10.'))


class TableOfContentsTests(TestCase):
    """articles.toc.extract_toc — heading ids + the sidebar "In This
    Article" nav they power (article_detail.html).
    """

    def test_headings_get_ids_and_toc_entries(self):
        html, entries = extract_toc('<h2>Introduction</h2><p>Text.</p><h2>Discussion</h2><p>More.</p>')
        self.assertEqual(html, '<h2 id="introduction">Introduction</h2><p>Text.</p><h2 id="discussion">Discussion</h2><p>More.</p>')
        self.assertEqual(entries, [
            {'level': 2, 'text': 'Introduction', 'id': 'introduction'},
            {'level': 2, 'text': 'Discussion', 'id': 'discussion'},
        ])

    def test_h3_included_with_correct_level(self):
        _html, entries = extract_toc('<h2>Section</h2><h3>Subsection</h3>')
        self.assertEqual([e['level'] for e in entries], [2, 3])

    def test_duplicate_heading_text_gets_a_unique_id(self):
        html, entries = extract_toc('<h2>Overview</h2><h2>Overview</h2>')
        self.assertEqual([e['id'] for e in entries], ['overview', 'overview-2'])
        self.assertIn('id="overview"', html)
        self.assertIn('id="overview-2"', html)

    def test_heading_with_existing_id_is_left_alone(self):
        html, entries = extract_toc('<h2 id="custom-anchor">Custom</h2>')
        self.assertEqual(entries[0]['id'], 'custom-anchor')
        self.assertIn('id="custom-anchor"', html)
        self.assertNotIn('id="custom-anchor" id=', html)

    def test_heading_text_is_stripped_of_inner_markup(self):
        _html, entries = extract_toc('<h2>Why <em>this</em> matters</h2>')
        self.assertEqual(entries[0]['text'], 'Why this matters')

    def test_non_heading_content_is_untouched(self):
        html, entries = extract_toc('<p>No headings here at all.</p>')
        self.assertEqual(html, '<p>No headings here at all.</p>')
        self.assertEqual(entries, [])

    def test_empty_content(self):
        self.assertEqual(extract_toc(''), ('', []))
        self.assertEqual(extract_toc(None), (None, []))


class ArticleDetailTocRenderingTests(TestCase):
    def test_toc_rendered_for_article_with_multiple_headings(self):
        article = make_article('toc-article', Article.ArticleType.NEWS_COMMENTARY)
        article.html_content = '<h2>First Section</h2><p>Text.</p><h2>Second Section</h2><p>More.</p>'
        article.save()
        response = self.client.get(article.get_absolute_url())
        self.assertContains(response, 'IN THIS ARTICLE')
        self.assertContains(response, 'href="#first-section"')
        self.assertContains(response, 'href="#second-section"')
        self.assertContains(response, 'id="first-section"')

    def test_no_toc_for_article_with_one_or_no_headings(self):
        article = make_article('no-toc-article', Article.ArticleType.NEWS_COMMENTARY)
        article.html_content = '<h2>Only Section</h2><p>Text.</p>'
        article.save()
        response = self.client.get(article.get_absolute_url())
        self.assertNotContains(response, 'IN THIS ARTICLE')


class ArticleManageListSearchTests(TestCase):
    def setUp(self):
        from users.models import User

        self.editor = User.objects.create_user(
            email='article-search-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def test_search_filters_by_title(self):
        match = Article.objects.create(
            title='Diabetes Breakthrough', slug='diabetes-breakthrough', abstract='...',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT,
        )
        Article.objects.create(
            title='Unrelated Story', slug='unrelated-story', abstract='...',
            article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT,
        )
        response = self.client.get(reverse('articles:manage_article_list'), {'q': 'diabetes'})
        self.assertEqual(list(response.context['articles']), [match])


class LanguageSwitcherTests(TestCase):
    """Cookie/session-based i18n (LocaleMiddleware + set_language) — nav/UI
    chrome only (templates/base.html), not article content. See ROADMAP.md
    Phase 7 and the Section/nav plan for the scope decision.
    """

    def test_default_language_is_english(self):
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, 'SUBSCRIBE')

    def test_switching_to_nepali_translates_a_tagged_chrome_string(self):
        self.client.post(reverse('set_language'), {'language': 'ne', 'next': reverse('articles:home')})
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, '<html lang="ne">')
        self.assertContains(response, 'सदस्यता लिनुहोस्')  # SUBSCRIBE, translated

    def test_language_choice_persists_via_cookie_across_requests(self):
        post_response = self.client.post(reverse('set_language'), {'language': 'ne', 'next': reverse('articles:home')})
        self.assertEqual(self.client.cookies['django_language'].value, 'ne')
        self.assertRedirects(post_response, reverse('articles:home'))
        # A second, independent request (no language re-selected) still gets
        # Nepali — proving the cookie, not just the redirect response, is
        # what carries the choice forward.
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, '<html lang="ne">')

    def test_switching_back_to_english_restores_default(self):
        self.client.post(reverse('set_language'), {'language': 'ne', 'next': reverse('articles:home')})
        self.client.post(reverse('set_language'), {'language': 'en', 'next': reverse('articles:home')})
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, 'SUBSCRIBE')

    def test_article_content_is_not_translated(self):
        article = make_article('nepali-chrome-scope-article', Article.ArticleType.NEWS_COMMENTARY)
        self.client.post(reverse('set_language'), {'language': 'ne', 'next': reverse('articles:home')})
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, article.title)


class ForYouViewTests(TestCase):
    """articles:for_you — a reader's personalized feed from their followed
    sections (sections.models.SectionFollow, ROADMAP.md Phase 10 Session 3).
    """

    def setUp(self):
        from users.models import User

        self.section = Section.objects.create(name_en='Test For You Section', slug='test-for-you-section')
        self.other_section = Section.objects.create(name_en='Test For You Other', slug='test-for-you-other')
        self.reader = User.objects.create_user(
            email='for-you-reader@example.com', password='pw', first_name='F', last_name='Y',
        )

    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.get(reverse('articles:for_you'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_shows_articles_from_followed_sections_only(self):
        SectionFollow.objects.create(user=self.reader, section=self.section)
        followed_article = make_article('for-you-followed', Article.ArticleType.NEWS_COMMENTARY)
        followed_article.section = self.section
        followed_article.save(update_fields=['section'])
        unfollowed_article = make_article('for-you-unfollowed', Article.ArticleType.NEWS_COMMENTARY)
        unfollowed_article.section = self.other_section
        unfollowed_article.save(update_fields=['section'])

        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:for_you'))
        articles = list(response.context['articles'])
        self.assertIn(followed_article, articles)
        self.assertNotIn(unfollowed_article, articles)

    def test_empty_state_when_following_nothing(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:for_you'))
        self.assertFalse(response.context['has_follows'])
        self.assertContains(response, 'not following any sections or keywords yet')

    def test_empty_state_differs_when_following_something_with_no_new_articles(self):
        SectionFollow.objects.create(user=self.reader, section=self.section)
        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:for_you'))
        self.assertTrue(response.context['has_follows'])
        self.assertContains(response, 'check back soon')


class BookmarkToggleTests(TestCase):
    """articles:article_bookmark_toggle — one endpoint handles both
    directions, keyed off whether a Bookmark row already exists (same
    shape as sections:section_follow_toggle, ROADMAP.md Phase 10 deferred
    list — bookmarks/read-later).
    """

    def setUp(self):
        from users.models import User

        self.article = make_article('bookmark-toggle-article', Article.ArticleType.NEWS_COMMENTARY)
        self.reader = User.objects.create_user(
            email='bookmark-reader@example.com', password='pw', first_name='B', last_name='R',
        )

    def test_saving_an_article_creates_a_bookmark(self):
        self.client.force_login(self.reader)
        self.client.post(reverse('articles:article_bookmark_toggle', args=[self.article.slug]))
        self.assertTrue(Bookmark.objects.filter(user=self.reader, article=self.article).exists())

    def test_toggling_again_removes_the_bookmark(self):
        Bookmark.objects.create(user=self.reader, article=self.article)
        self.client.force_login(self.reader)
        self.client.post(reverse('articles:article_bookmark_toggle', args=[self.article.slug]))
        self.assertFalse(Bookmark.objects.filter(user=self.reader, article=self.article).exists())

    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.post(reverse('articles:article_bookmark_toggle', args=[self.article.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_article_detail_reflects_bookmark_state(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertFalse(response.context['is_bookmarked'])
        Bookmark.objects.create(user=self.reader, article=self.article)
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertTrue(response.context['is_bookmarked'])

    def test_subscription_article_can_be_bookmarked_without_access(self):
        # Deliberately not paywall-gated — a reader should be able to save
        # something for later before they've subscribed to read it.
        gated_article = make_article('bookmark-gated-article', Article.ArticleType.NEWS_COMMENTARY)
        gated_article.access_type = Article.AccessType.SUBSCRIPTION
        gated_article.save(update_fields=['access_type'])
        self.client.force_login(self.reader)
        response = self.client.post(reverse('articles:article_bookmark_toggle', args=[gated_article.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Bookmark.objects.filter(user=self.reader, article=gated_article).exists())


class ReadingListViewTests(TestCase):
    """articles:reading_list — a reader's saved articles, most recently
    saved first.
    """

    def setUp(self):
        from users.models import User

        self.reader = User.objects.create_user(
            email='reading-list-reader@example.com', password='pw', first_name='R', last_name='L',
        )

    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.get(reverse('articles:reading_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_shows_only_this_readers_bookmarks(self):
        from users.models import User

        other_reader = User.objects.create_user(
            email='reading-list-other@example.com', password='pw', first_name='O', last_name='R',
        )
        own_article = make_article('reading-list-own', Article.ArticleType.NEWS_COMMENTARY)
        other_article = make_article('reading-list-other-article', Article.ArticleType.NEWS_COMMENTARY)
        Bookmark.objects.create(user=self.reader, article=own_article)
        Bookmark.objects.create(user=other_reader, article=other_article)

        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:reading_list'))
        articles = list(response.context['articles'])
        self.assertIn(own_article, articles)
        self.assertNotIn(other_article, articles)

    def test_most_recently_saved_appears_first(self):
        first_saved = make_article('reading-list-first', Article.ArticleType.NEWS_COMMENTARY)
        second_saved = make_article('reading-list-second', Article.ArticleType.NEWS_COMMENTARY)
        Bookmark.objects.create(user=self.reader, article=first_saved)
        Bookmark.objects.create(user=self.reader, article=second_saved)

        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:reading_list'))
        articles = list(response.context['articles'])
        self.assertEqual(articles, [second_saved, first_saved])

    def test_empty_state_when_nothing_saved(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:reading_list'))
        self.assertContains(response, 'Nothing saved yet')

    def test_removing_a_bookmark_from_the_reading_list(self):
        article = make_article('reading-list-remove', Article.ArticleType.NEWS_COMMENTARY)
        Bookmark.objects.create(user=self.reader, article=article)
        self.client.force_login(self.reader)
        self.client.post(reverse('articles:article_bookmark_toggle', args=[article.slug]))
        self.assertFalse(Bookmark.objects.filter(user=self.reader, article=article).exists())


class KeywordFollowToggleTests(TestCase):
    """articles:keyword_follow_toggle — same one-endpoint shape as
    sections:section_follow_toggle, but gated on keyword usage
    (ROADMAP.md Phase 10 Session 5: a keyword used on one article or fewer
    has nothing meaningful to follow).
    """

    def setUp(self):
        from users.models import User

        self.reader = User.objects.create_user(
            email='keyword-follow-reader@example.com', password='pw', first_name='K', last_name='F',
        )

    def _eligible_keyword(self, name='eligible-keyword'):
        keyword = make_keyword(name)
        make_article(f'{name}-article-1', Article.ArticleType.NEWS_COMMENTARY).keyword_tags.add(keyword)
        make_article(f'{name}-article-2', Article.ArticleType.NEWS_COMMENTARY).keyword_tags.add(keyword)
        return keyword

    def test_following_an_eligible_keyword_creates_a_follow(self):
        keyword = self._eligible_keyword()
        self.client.force_login(self.reader)
        self.client.post(reverse('articles:keyword_follow_toggle', args=[keyword.slug]))
        self.assertTrue(KeywordFollow.objects.filter(user=self.reader, keyword=keyword).exists())

    def test_toggling_again_removes_the_follow(self):
        keyword = self._eligible_keyword()
        KeywordFollow.objects.create(user=self.reader, keyword=keyword)
        self.client.force_login(self.reader)
        self.client.post(reverse('articles:keyword_follow_toggle', args=[keyword.slug]))
        self.assertFalse(KeywordFollow.objects.filter(user=self.reader, keyword=keyword).exists())

    def test_anonymous_visitor_is_redirected_to_login(self):
        keyword = self._eligible_keyword()
        response = self.client.post(reverse('articles:keyword_follow_toggle', args=[keyword.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_keyword_used_once_cannot_be_followed(self):
        keyword = make_keyword('single-use-keyword')
        make_article('single-use-keyword-article', Article.ArticleType.NEWS_COMMENTARY).keyword_tags.add(keyword)
        self.client.force_login(self.reader)
        response = self.client.post(reverse('articles:keyword_follow_toggle', args=[keyword.slug]))
        self.assertEqual(response.status_code, 404)

    def test_unused_keyword_cannot_be_followed(self):
        keyword = make_keyword('unused-keyword')
        self.client.force_login(self.reader)
        response = self.client.post(reverse('articles:keyword_follow_toggle', args=[keyword.slug]))
        self.assertEqual(response.status_code, 404)

    def test_existing_follow_can_be_removed_even_below_the_threshold(self):
        # A keyword that drops back to/below KEYWORD_FOLLOW_MIN_ARTICLES
        # after a follow already exists (e.g. an article unpublished) must
        # still be unfollowable — only *creating* a new follow is
        # eligibility-gated, per KeywordFollow's own docstring.
        keyword = make_keyword('now-unused-keyword')
        KeywordFollow.objects.create(user=self.reader, keyword=keyword)
        self.client.force_login(self.reader)
        response = self.client.post(reverse('articles:keyword_follow_toggle', args=[keyword.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(KeywordFollow.objects.filter(user=self.reader, keyword=keyword).exists())

    def test_article_list_shows_follow_button_only_when_eligible(self):
        eligible = self._eligible_keyword('shown-keyword')
        ineligible = make_keyword('hidden-keyword')
        make_article('hidden-keyword-article', Article.ArticleType.NEWS_COMMENTARY).keyword_tags.add(ineligible)
        self.client.force_login(self.reader)

        response = self.client.get(reverse('articles:article_list'), {'keyword': eligible.slug})
        self.assertTrue(response.context['keyword_follow_eligible'])

        response = self.client.get(reverse('articles:article_list'), {'keyword': ineligible.slug})
        self.assertFalse(response.context['keyword_follow_eligible'])
        self.assertNotContains(response, reverse('articles:keyword_follow_toggle', args=[ineligible.slug]))

    def test_article_list_reflects_follow_state(self):
        keyword = self._eligible_keyword()
        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:article_list'), {'keyword': keyword.slug})
        self.assertFalse(response.context['is_following_keyword'])
        KeywordFollow.objects.create(user=self.reader, keyword=keyword)
        response = self.client.get(reverse('articles:article_list'), {'keyword': keyword.slug})
        self.assertTrue(response.context['is_following_keyword'])


class ForYouKeywordFollowTests(TestCase):
    """ForYouView combines Section- and Keyword-followed articles into one
    de-duplicated feed (ROADMAP.md Phase 10 Session 5).
    """

    def setUp(self):
        from users.models import User

        self.reader = User.objects.create_user(
            email='for-you-keyword-reader@example.com', password='pw', first_name='F', last_name='K',
        )
        self.keyword = make_keyword('for-you-followed-keyword')

    def test_shows_articles_matching_a_followed_keyword(self):
        KeywordFollow.objects.create(user=self.reader, keyword=self.keyword)
        matching = make_article('for-you-keyword-match', Article.ArticleType.NEWS_COMMENTARY)
        matching.keyword_tags.add(self.keyword)
        unrelated = make_article('for-you-keyword-unrelated', Article.ArticleType.NEWS_COMMENTARY)

        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:for_you'))
        articles = list(response.context['articles'])
        self.assertIn(matching, articles)
        self.assertNotIn(unrelated, articles)

    def test_article_matching_both_a_followed_section_and_keyword_appears_once(self):
        section = Section.objects.create(name_en='For You Dedup Section', slug='for-you-dedup-section')
        SectionFollow.objects.create(user=self.reader, section=section)
        KeywordFollow.objects.create(user=self.reader, keyword=self.keyword)
        article = make_article('for-you-dedup-article', Article.ArticleType.NEWS_COMMENTARY)
        article.section = section
        article.save(update_fields=['section'])
        article.keyword_tags.add(self.keyword)

        self.client.force_login(self.reader)
        response = self.client.get(reverse('articles:for_you'))
        articles = list(response.context['articles'])
        self.assertEqual(articles.count(article), 1)


class ArticleGiftTests(TestCase):
    """Gift-article creation and redemption (ROADMAP.md Phase 10) — a
    subscriber generates a shareable link (articles:article_gift_create),
    anyone who opens it (articles:article_gift_view, routes back into
    ArticleDetailView with a gift_token kwarg) reads the article free.
    """

    def setUp(self):
        from users.models import User

        self.subscriber = User.objects.create_user(
            email='gift-subscriber@example.com', password='pw', first_name='G', last_name='S',
        )
        plan = SubscriptionPlan.objects.create(
            name='Gifting Plan', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=5, duration_days=30, gift_articles_per_month=2,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=self.subscriber, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.article = make_article('gift-test-article', Article.ArticleType.NEWS_COMMENTARY)
        self.article.access_type = Article.AccessType.SUBSCRIPTION
        self.article.html_content = 'Secret gifted text'
        self.article.save(update_fields=['access_type', 'html_content'])

    def test_subscriber_can_create_a_gift_link(self):
        self.client.force_login(self.subscriber)
        response = self.client.post(reverse('articles:article_gift_create', args=[self.article.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ArticleGift.objects.filter(gifter=self.subscriber, article=self.article).exists())

    def test_reader_without_gift_allowance_cannot_create_a_link(self):
        from users.models import User

        reader = User.objects.create_user(email='no-gift-reader@example.com', password='pw', first_name='N', last_name='R')
        self.client.force_login(reader)
        self.client.post(reverse('articles:article_gift_create', args=[self.article.slug]))
        self.assertFalse(ArticleGift.objects.filter(article=self.article).exists())

    def test_anonymous_reader_gets_full_text_via_a_valid_gift_link(self):
        gift = ArticleGift.objects.create(
            gifter=self.subscriber, article=self.article, period='2026-09',
            expires_at=timezone.now() + datetime.timedelta(days=14),
        )
        response = self.client.get(reverse('articles:article_gift_view', args=[self.article.slug, gift.token]))
        self.assertContains(response, 'Secret gifted text')
        self.assertContains(response, self.subscriber.get_full_name())

    def test_gift_view_does_not_consume_the_visitors_free_sample_quota(self):
        from billing.models import MeteredArticleRead

        gift = ArticleGift.objects.create(
            gifter=self.subscriber, article=self.article, period='2026-09',
            expires_at=timezone.now() + datetime.timedelta(days=14),
        )
        self.client.get(reverse('articles:article_gift_view', args=[self.article.slug, gift.token]))
        self.assertFalse(MeteredArticleRead.objects.filter(article=self.article).exists())

    def test_expired_gift_link_falls_back_to_normal_gating(self):
        # "Falls back to normal gating" legitimately includes the metered
        # free-sample allowance, which can independently grant full text on
        # a fresh anonymous session — so the thing to assert isn't "no
        # access at all," it's that the *expired gift* specifically wasn't
        # what granted it (no gift_banner).
        gift = ArticleGift.objects.create(
            gifter=self.subscriber, article=self.article, period='2026-09',
            expires_at=timezone.now() - datetime.timedelta(days=1),
        )
        response = self.client.get(reverse('articles:article_gift_view', args=[self.article.slug, gift.token]))
        self.assertIsNone(response.context['gift_banner'])

    def test_invalid_token_falls_back_to_normal_gating(self):
        response = self.client.get(
            reverse('articles:article_gift_view', args=[self.article.slug, 'not-a-real-token']),
        )
        self.assertIsNone(response.context['gift_banner'])

    def test_regenerating_returns_the_same_link_and_notice(self):
        self.client.force_login(self.subscriber)
        self.client.post(reverse('articles:article_gift_create', args=[self.article.slug]))
        first_gift = ArticleGift.objects.get(gifter=self.subscriber, article=self.article)
        self.client.post(reverse('articles:article_gift_create', args=[self.article.slug]))
        self.assertEqual(ArticleGift.objects.filter(gifter=self.subscriber, article=self.article).count(), 1)
        second_gift = ArticleGift.objects.get(gifter=self.subscriber, article=self.article)
        self.assertEqual(first_gift.token, second_gift.token)

    def test_article_page_shows_gift_control_for_eligible_subscriber(self):
        self.client.force_login(self.subscriber)
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertIsNotNone(response.context['gift_remaining'])
        self.assertEqual(response.context['gift_remaining'], 2)

    def test_article_page_hides_gift_control_for_non_subscriber(self):
        from users.models import User

        reader = User.objects.create_user(email='hide-gift-reader@example.com', password='pw', first_name='H', last_name='R')
        self.client.force_login(reader)
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertIsNone(response.context['gift_remaining'])


class ArchivedArticleTests(TestCase):
    """Archival access (ROADMAP.md Phase 10 Session 7) — an archived
    article stays reachable at its own permalink and in search, but its
    full text is gated behind SubscriptionPlan.grants_full_archive.
    """

    def setUp(self):
        self.article = make_article('archived-test-article', Article.ArticleType.NEWS_COMMENTARY)
        self.article.status = Article.Status.ARCHIVED
        self.article.access_type = Article.AccessType.OPEN_ACCESS
        self.article.html_content = 'Secret archived text'
        self.article.save(update_fields=['status', 'access_type', 'html_content'])

    def test_archived_article_is_reachable_at_its_permalink(self):
        # Previously a blanket 404 — ArticleDetailView.get_queryset() only
        # matched PUBLISHED, so archiving silently removed the article from
        # the public site entirely, not just its full text.
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertEqual(response.status_code, 200)

    def test_archived_article_hides_full_text_without_the_perk(self):
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertNotContains(response, 'Secret archived text')
        self.assertContains(response, 'Archive Access Required')

    def test_archived_article_shows_full_text_with_the_perk(self):
        from billing.models import SubscriptionPlan, UserSubscription
        from users.models import User

        reader = User.objects.create_user(email='archive-detail-reader@example.com', password='pw', first_name='A', last_name='R')
        plan = SubscriptionPlan.objects.create(
            name='Archive Plan', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=5, duration_days=30, grants_full_archive=True,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(user=reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30))
        self.client.force_login(reader)
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertContains(response, 'Secret archived text')

    def test_draft_article_still_404s(self):
        # Confirms the ARCHIVED addition didn't accidentally widen the
        # queryset beyond PUBLISHED + ARCHIVED.
        draft = make_article('archived-scope-draft', Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.DRAFT)
        response = self.client.get(reverse('articles:article_detail', args=[draft.slug]))
        self.assertEqual(response.status_code, 404)

    def test_search_includes_archived_articles(self):
        response = self.client.get(reverse('articles:search'), {'q': 'archived-test-article'.replace('-', ' ')})
        self.assertIn(self.article, list(response.context['articles']))

    def test_archive_list_shows_archived_articles(self):
        response = self.client.get(reverse('articles:archive_list'))
        self.assertContains(response, self.article.title)

    def test_archive_list_excludes_published_articles(self):
        published = make_article('archive-list-published', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:archive_list'))
        articles = list(response.context['articles'])
        self.assertNotIn(published, articles)


def make_text_article(slug, title, abstract, body='', status=Article.Status.PUBLISHED, keywords=()):
    article = Article.objects.create(
        title=title, slug=slug, abstract=abstract, html_content=body,
        article_type=Article.ArticleType.NEWS_COMMENTARY, status=status,
    )
    if keywords:
        article.keyword_tags.set([Keyword.objects.get_or_create(slug=slugify(k), defaults={'name': k})[0] for k in keywords])
    return article


class TextSimilarityTests(TestCase):
    """articles/similarity.py — TF-IDF cosine similarity used for automatic
    "Related reading" and the editor's suggestions.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.tb_review = make_text_article(
            'sim-tb-review', 'Community Tuberculosis Screening Review',
            'A systematic review of tuberculosis screening in rural districts.',
            '<p>Active case finding for tuberculosis improves screening yield.</p>', keywords=['Tuberculosis'],
        )
        self.tb_news = make_text_article(
            'sim-tb-news', 'New Tuberculosis Screening Guidelines Issued',
            'The ministry issued guidelines for tuberculosis screening.',
            '<p>Screening for tuberculosis will expand to every district.</p>', keywords=['Tuberculosis'],
        )
        self.budget = make_text_article(
            'sim-budget', 'Parliament Passes Infrastructure Budget',
            'Road and bridge spending rises in the new fiscal year.',
            '<p>Highways and bridges receive the largest allocation.</p>',
        )

    def test_tokenize_strips_html_stopwords_and_folds_plurals(self):
        from .similarity import tokenize
        self.assertEqual(tokenize('<p>The Studies of <b>Clinics</b> and the clinic</p>'), ['study', 'clinic', 'clinic'])

    def test_tokenize_keeps_devanagari_words_whole(self):
        from .similarity import tokenize
        # Vowel signs (ा, ्) are combining marks — must not split words; र is a stopword.
        self.assertEqual(tokenize('स्वास्थ्य र सजगता'), ['स्वास्थ्य', 'सजगता'])

    def test_topical_match_ranks_first_and_unrelated_is_excluded(self):
        from .similarity import similar_articles
        results = similar_articles(self.tb_review)
        self.assertEqual([a for a, _ in results], [self.tb_news])
        self.assertGreater(results[0][1], 0.08)

    def test_scores_are_symmetric(self):
        from .similarity import similar_articles
        forward = dict((a.pk, s) for a, s in similar_articles(self.tb_review))
        backward = dict((a.pk, s) for a, s in similar_articles(self.tb_news))
        self.assertAlmostEqual(forward[self.tb_news.pk], backward[self.tb_review.pk], places=3)

    def test_drafts_are_never_suggested_but_can_get_suggestions(self):
        from .similarity import similar_articles
        draft = make_text_article(
            'sim-tb-draft', 'Tuberculosis Screening Draft', 'Draft about tuberculosis screening.',
            status=Article.Status.DRAFT,
        )
        self.assertNotIn(draft, [a for a, _ in similar_articles(self.tb_review)])
        self.assertIn(self.tb_review, [a for a, _ in similar_articles(draft)])

    def test_results_refresh_when_an_article_is_edited(self):
        from .similarity import similar_articles
        self.assertEqual(similar_articles(self.budget), [])
        self.tb_news.title = 'Parliament Budget Adds Tuberculosis Screening Highways Bridges'
        self.tb_news.save()
        self.assertIn(self.tb_news, [a for a, _ in similar_articles(self.budget)])


class RelatedReadingTests(TestCase):
    """Article page "Related reading": editor picks first, text similarity
    otherwise (articles/views.py:related_articles_for).
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.article = make_text_article(
            'rel-main', 'Tuberculosis Screening Expands', 'Tuberculosis screening reaches more districts.',
        )
        self.similar = make_text_article(
            'rel-similar', 'Tuberculosis Screening Methods Compared', 'Comparing tuberculosis screening methods.',
        )
        self.picked = make_text_article('rel-picked', 'Monsoon Flood Relief', 'Relief camps open after floods.')

    def _related(self):
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        return response.context['related_articles']

    def test_falls_back_to_text_similarity(self):
        self.assertEqual(self._related(), [self.similar])

    def test_editor_picks_replace_similarity(self):
        self.article.related_articles.set([self.picked])
        self.assertEqual(self._related(), [self.picked])

    def test_unpublished_picks_are_ignored(self):
        draft = make_text_article('rel-draft-pick', 'Draft Pick', 'x', status=Article.Status.DRAFT)
        self.article.related_articles.set([draft])
        self.assertEqual(self._related(), [self.similar])

    def test_related_is_one_directional(self):
        self.article.related_articles.set([self.picked])
        self.assertEqual(list(self.picked.related_articles.all()), [])


class ArticleFormRelatedArticlesTests(TestCase):
    def setUp(self):
        self.published = make_text_article('form-rel-pub', 'Published One', 'x')
        self.draft = make_text_article('form-rel-draft', 'Draft One', 'x', status=Article.Status.DRAFT)

    def _data(self, **overrides):
        data = {
            'title': 'A New Article', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'abstract': 'An abstract.',
        }
        data.update(overrides)
        return data

    def test_saves_picked_published_articles_and_keywords_together(self):
        import json
        form = ArticleForm(data=self._data(
            related_articles=json.dumps([{'value': 'Published One', 'id': self.published.pk},
                                         {'value': 'Draft One', 'id': self.draft.pk}]),
            keywords='[{"value": "Diabetes"}]',
        ))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save()
        self.assertEqual(list(article.related_articles.all()), [self.published])
        self.assertEqual([k.name for k in article.keyword_tags.all()], ['Diabetes'])

    def test_commit_false_defers_related_until_save_m2m(self):
        form = ArticleForm(data=self._data(related_articles=str(self.published.pk)))
        self.assertTrue(form.is_valid(), form.errors)
        article = form.save(commit=False)
        article.save()
        self.assertEqual(article.related_articles.count(), 0)
        form.save_m2m()
        self.assertEqual(article.related_articles.count(), 1)

    def test_article_cannot_relate_to_itself(self):
        form = ArticleForm(data=self._data(title='Published One', related_articles=str(self.published.pk)),
                           instance=self.published)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(list(form.save().related_articles.all()), [])

    def test_edit_form_prefills_picks_as_tagify_json(self):
        self.draft.related_articles.set([self.published])
        form = ArticleForm(instance=self.draft)
        self.assertIn(f'"id": {self.published.pk}', form.fields['related_articles'].initial)


class RelatedArticleEndpointsTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        from users.models import User
        cache.clear()
        self.editor = User.objects.create_user(
            email='related-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='related-reader@example.com', password='pw', first_name='R', last_name='D')
        self.a = make_text_article('ep-a', 'Malaria Vaccine Rollout', 'Malaria vaccine rollout begins.')
        self.b = make_text_article('ep-b', 'Malaria Vaccine Trial Results', 'Malaria vaccine trial results.')

    def test_readers_are_forbidden(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse('articles:manage_related_article_autocomplete')).status_code, 403)
        self.assertEqual(self.client.get(reverse('articles:manage_related_article_suggestions')).status_code, 403)

    def test_autocomplete_matches_title_and_excludes_current(self):
        self.client.force_login(self.editor)
        response = self.client.get(
            reverse('articles:manage_related_article_autocomplete'), {'q': 'malaria', 'exclude': self.a.pk},
        )
        self.assertEqual([item['id'] for item in response.json()], [self.b.pk])

    def test_suggestions_include_similarity_score(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('articles:manage_related_article_suggestions'), {'article': self.a.pk})
        suggestions = response.json()['suggestions']
        self.assertEqual([s['id'] for s in suggestions], [self.b.pk])
        self.assertTrue(0 < suggestions[0]['score'] <= 100)

    def test_suggestions_for_unsaved_article(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('articles:manage_related_article_suggestions'))
        self.assertEqual(response.json(), {'suggestions': [], 'reason': 'unsaved'})

    def test_article_form_has_related_tab(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('articles:manage_article_update', args=[self.a.slug]))
        self.assertContains(response, 'id="related-panel"')
        self.assertContains(response, 'id="id_related_articles"')


class ReaderTextSizeAndNepaliTypographyTests(TestCase):
    def test_text_size_controls_render(self):
        article = make_article('text-size-article', Article.ArticleType.NEWS_COMMENTARY)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, 'id="text-size-controls"')
        for action in ('down', 'reset', 'up'):
            self.assertContains(response, f'data-text-size="{action}"')

    def test_nepali_script_article_gets_lang_ne(self):
        article = Article.objects.create(
            title='दशैं तथा चाडपर्वको समयमा स्वास्थ्य सजगता', slug='nepali-script-article',
            abstract='चाडपर्वमा स्वास्थ्यको ख्याल राख्नुहोस्।', article_type=Article.ArticleType.NEWS_COMMENTARY,
            status=Article.Status.PUBLISHED,
        )
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, 'id="article-main" lang="ne"')

    def test_content_lang_filter(self):
        from .templatetags.text_filters import content_lang
        self.assertEqual(content_lang('स्वास्थ्य सजगता'), 'ne')
        self.assertEqual(content_lang('Health news with one word स्वास्थ्य'), 'en')
        self.assertEqual(content_lang('', 'ne'), 'ne')


class CommentEmailTemplateTests(TestCase):
    """templates/django_comments_xtd/email_*.html — branded overrides of the
    comments package's plain default emails.
    """

    def setUp(self):
        from users.models import User
        self.article = make_article('emailed-article', Article.ArticleType.NEWS_COMMENTARY)
        self.first = User.objects.create_user(email='first@example.com', password='pw', first_name='First', last_name='Reader')
        self.second = User.objects.create_user(email='second@example.com', password='pw', first_name='Second', last_name='Reader')

    def test_confirmation_email_is_branded_with_absolute_link(self):
        from django.conf import settings
        from django.core import mail

        self.client.post(
            reverse('comments-post-comment'),
            _comment_post_data(self.article, 'Please publish me.', name='Anon Reader', email='anon@example.com'),
        )
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'Confirm your comment')
        html = message.alternatives[0][0]
        self.assertIn('Confirm your comment to publish it', html)
        self.assertIn('Please publish me.', html)
        self.assertIn(f'{settings.SITE_BASE_URL}/comments/confirm/', html)
        self.assertIn(self.article.title, html)
        self.assertIn(f'{settings.SITE_BASE_URL}/comments/confirm/', message.body)

    def test_followup_email_links_to_the_new_comment_and_mute(self):
        from django.conf import settings
        from django.core import mail
        from django_comments_xtd.models import XtdComment

        self.client.force_login(self.first)
        self.client.post(reverse('comments-post-comment'), _comment_post_data(self.article, 'First!', followup=True))
        self.client.force_login(self.second)
        mail.outbox = []
        self.client.post(reverse('comments-post-comment'), _comment_post_data(self.article, 'A reply.'))

        reply = XtdComment.objects.get(comment='A reply.')
        message = next(m for m in mail.outbox if m.to == ['first@example.com'])
        self.assertEqual(message.subject, 'New comment in a discussion you follow')
        html = message.alternatives[0][0]
        self.assertIn('A reply.', html)
        self.assertIn(f'{settings.SITE_BASE_URL}{self.article.get_absolute_url()}#c{reply.pk}', html)
        self.assertIn(f'{settings.SITE_BASE_URL}/comments/mute/', html)


class NepaliInterfaceTests(TestCase):
    """The reader-facing UI is translated (locale/ne) — switching language
    changes the interface text, not just the fonts.
    """

    def test_article_page_renders_in_nepali(self):
        from django.conf import settings
        article = make_article('nepali-ui-article', Article.ArticleType.NEWS_COMMENTARY)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'ne'
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        for text in ('टिप्पणीहरू', 'गृहपृष्ठ', 'अक्षरको आकार', 'सम्पादकीय टोली'):
            self.assertContains(response, text)
        self.assertNotContains(response, 'LOG IN TO SAVE')


class OptionalAbstractTests(TestCase):
    """Abstract is optional (short news pieces often have none) — listings,
    feeds and meta tags fall back to Article.summary, which only ever
    excerpts the body of open-access articles.
    """

    def _article(self, slug, **fields):
        defaults = {
            'title': slug.replace('-', ' ').title(), 'slug': slug, 'abstract': '',
            'article_type': Article.ArticleType.NEWS_COMMENTARY, 'status': Article.Status.PUBLISHED,
            'access_type': Article.AccessType.OPEN_ACCESS,
        }
        defaults.update(fields)
        return Article.objects.create(**defaults)

    def test_form_accepts_empty_abstract(self):
        form = ArticleForm(data={
            'title': 'Quick News', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'abstract': '',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_summary_prefers_abstract(self):
        article = self._article('with-abstract', abstract='  The standfirst. ', html_content='<p>Body text.</p>')
        self.assertEqual(article.summary, 'The standfirst.')

    def test_summary_excerpts_open_access_body(self):
        article = self._article('no-abstract', html_content='<p>Clinics <strong>reopened</strong> today.</p>')
        self.assertEqual(article.summary, 'Clinics reopened today.')

    def test_summary_never_excerpts_paywalled_body(self):
        article = self._article(
            'paid-no-abstract', access_type=Article.AccessType.SUBSCRIPTION,
            html_content='<p>Secret premium paragraph.</p>',
        )
        self.assertEqual(article.summary, '')

    def test_detail_and_list_render_without_abstract(self):
        article = self._article('bare-news', html_content='<p>Opening line of the story.</p>')
        detail = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'content="Opening line of the story."')
        listing = self.client.get(reverse('articles:article_list'))
        self.assertContains(listing, 'Opening line of the story.')


class AuthorProfileTests(TestCase):
    """Bylines point at Author profiles, which need no login account."""

    def setUp(self):
        from users.models import User

        self.article = Article.objects.create(
            title='Guest Column', slug='guest-column', abstract='A guest column.',
            article_type=Article.ArticleType.EDITORIAL, status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.OPEN_ACCESS,
        )
        self.editor = User.objects.create_user(
            email='byline-editor@example.com', password='pw', first_name='Byline', last_name='Editor',
            role=User.Role.EDITOR,
        )

    def test_author_without_account_gets_byline_and_public_page(self):
        author = Author.objects.create(name='Dr. Guest Writer', affiliation='Kathmandu University')
        ArticleAuthor.objects.create(article=self.article, author=author, is_corresponding=True)
        detail = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertContains(detail, 'Dr. Guest Writer')
        self.assertContains(detail, 'Kathmandu University')
        self.assertContains(detail, reverse('articles:author_detail', args=[author.slug]))
        page = self.client.get(reverse('articles:author_detail', args=[author.slug]))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(list(page.context['author_articles']), [self.article])

    def test_author_without_published_bylines_has_no_page(self):
        author = Author.objects.create(name='Not Yet Published')
        self.assertEqual(self.client.get(reverse('articles:author_detail', args=[author.slug])).status_code, 404)

    def test_author_name_in_citation_and_search(self):
        ArticleAuthor.objects.create(article=self.article, author=Author.objects.create(name='Sita Guest'))
        citation = self.client.get(reverse('articles:article_citation', args=[self.article.slug, 'text']))
        self.assertIn('Sita Guest', citation.content.decode())
        search = self.client.get(reverse('articles:search'), {'q': 'Sita Guest'})
        self.assertIn(self.article, list(search.context['articles']))

    def test_legacy_user_id_url_redirects_to_author_page(self):
        profile = Author.for_user(self.editor)
        ArticleAuthor.objects.create(article=self.article, author=profile)
        response = self.client.get(f'/authors/{self.editor.pk}/')
        self.assertRedirects(response, reverse('articles:author_detail', args=[profile.slug]), status_code=301)

    def test_numeric_name_never_gets_an_all_digit_slug(self):
        self.assertEqual(Author.objects.create(name='2024').slug, 'author-2024')


class BylineBoxTests(TestCase):
    """The Authors box in the article form (articles/bylines.py): pick
    existing authors, add new ones (name/affiliation/email only), order and
    corresponding flag — all saved with the article itself."""

    def setUp(self):
        from users.models import User

        self.editor = User.objects.create_user(
            email='bylines-editor@example.com', password='pw', first_name='B', last_name='E', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)
        self.existing = Author.objects.create(name='Dr. Existing Writer', affiliation='TU Teaching Hospital')

    def _create(self, bylines, **data):
        return self.client.post(reverse('articles:manage_article_create'), {
            'title': data.pop('title', 'Byline Story'), 'action': 'draft', 'bylines': json.dumps(bylines), **data,
        })

    def test_new_article_saves_existing_and_new_authors_in_order(self):
        response = self._create([
            {'key': 'n1', 'name': ' Sita  Rai ', 'affiliation': 'Freelance', 'email': 'sita@example.com'},
            {'id': self.existing.pk, 'corresponding': True},
        ])
        self.assertEqual(response.status_code, 302)
        article = Article.objects.get(title='Byline Story')
        bylines = list(article.articleauthor_set.order_by('order'))
        self.assertEqual([b.author.name for b in bylines], ['Sita Rai', 'Dr. Existing Writer'])
        self.assertEqual([b.is_corresponding for b in bylines], [False, True])
        new_author = bylines[0].author
        self.assertEqual((new_author.affiliation, new_author.email, new_author.user), ('Freelance', 'sita@example.com', None))

    def test_new_author_with_an_existing_name_is_reused(self):
        self._create([{'key': 'n1', 'name': 'dr. existing writer'}])
        self.assertEqual(Author.objects.count(), 1)
        self.assertEqual(Article.objects.get().articleauthor_set.get().author, self.existing)

    def test_same_name_with_a_different_email_is_a_different_person(self):
        self.existing.email = 'one@example.com'
        self.existing.save()
        self._create([{'key': 'n1', 'name': 'Dr. Existing Writer', 'email': 'two@example.com'}])
        self.assertEqual(Author.objects.filter(name='Dr. Existing Writer').count(), 2)

    def test_editing_reorders_removes_and_leaves_bylines_alone_when_absent(self):
        other = Author.objects.create(name='Second Writer')
        self._create([{'id': self.existing.pk}, {'id': other.pk}])
        article = Article.objects.get()
        url = reverse('articles:manage_article_update', args=[article.slug])
        self.client.post(url, {'title': 'Byline Story', 'action': 'draft', 'bylines': json.dumps([{'id': other.pk}])})
        self.assertEqual([b.author for b in article.articleauthor_set.all()], [other])
        # A POST without the field at all (e.g. an old client) changes nothing.
        self.client.post(url, {'title': 'Byline Story', 'action': 'draft'})
        self.assertEqual([b.author for b in article.articleauthor_set.all()], [other])
        self.client.post(url, {'title': 'Byline Story', 'action': 'draft', 'bylines': '[]'})
        self.assertFalse(article.articleauthor_set.exists())

    def test_invalid_entries_save_nothing(self):
        response = self._create([{'key': 'n1', 'name': '  '}])
        self.assertEqual(response.status_code, 200)
        self.assertIn('bylines', response.context['form'].errors)
        self.assertFalse(Article.objects.exists())
        response = self._create([{'key': 'n1', 'name': 'Bad Email', 'email': 'not-an-email'}])
        self.assertIn('bylines', response.context['form'].errors)
        self.assertEqual(Author.objects.count(), 1)

    def test_inactive_author_cannot_be_added_but_stays_where_already_credited(self):
        self._create([{'id': self.existing.pk}])
        article = Article.objects.get()
        self.existing.is_active = False
        self.existing.save()
        url = reverse('articles:manage_article_update', args=[article.slug])
        response = self.client.post(url, {'title': 'Byline Story', 'action': 'draft', 'bylines': json.dumps([{'id': self.existing.pk}])})
        self.assertEqual(response.status_code, 302)
        response = self._create([{'id': self.existing.pk}], title='Another Story')
        self.assertIn('bylines', response.context['form'].errors)

    def test_autosave_creates_new_author_once_and_returns_its_id(self):
        url = reverse('articles:manage_article_autosave')
        data = self.client.post(url, {
            'title': 'Autosaved Story', 'bylines': json.dumps([{'key': 'k1', 'name': 'Autosave Author'}]),
        }).json()
        author = Author.objects.get(name='Autosave Author')
        self.assertEqual(data['created_authors'], {'k1': author.pk})
        self.client.post(url, {
            'title': 'Autosaved Story', 'article_pk': data['article_pk'], 'edit_token': data['edit_token'],
            'bylines': json.dumps([{'id': author.pk}]),
        })
        self.assertEqual(Author.objects.filter(name='Autosave Author').count(), 1)

    def test_byline_changes_show_in_history(self):
        from .revisions import compare

        self._create([{'id': self.existing.pk}])
        article = Article.objects.get()
        self.client.post(reverse('articles:manage_article_update', args=[article.slug]), {
            'title': 'Byline Story', 'action': 'draft',
            'bylines': json.dumps([{'id': self.existing.pk, 'corresponding': True}, {'key': 'n', 'name': 'Added Later'}]),
        })
        newer, older = article.revisions.all()[:2]
        self.assertEqual(newer.bylines, 'Dr. Existing Writer (corresponding), Added Later')
        changes = compare(older, newer)
        self.assertEqual([c['label'] for c in changes], ['Authors'])

    def test_non_publisher_cannot_change_bylines_on_a_live_article(self):
        article = Article.objects.create(
            title='Live Byline', slug='live-byline', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.OPEN_ACCESS, html_content='<p>Text.</p>',
        )
        self.client.post(reverse('articles:manage_article_update', args=[article.slug]), {
            'title': 'Live Byline', 'article_type': article.article_type, 'access_type': 'open_access',
            'html_content': '<p>Text.</p>', 'action': 'save', 'bylines': json.dumps([{'id': self.existing.pk}]),
        })
        self.assertFalse(article.articleauthor_set.exists())

    def test_preview_shows_unsaved_authors_without_creating_them(self):
        response = self.client.post(reverse('articles:manage_article_preview'), {
            'title': 'Preview Story', 'article_type': 'news_commentary', 'access_type': 'open_access',
            'bylines': json.dumps([{'key': 'p', 'name': 'Preview Only Author'}]),
        })
        self.assertContains(response, 'Preview Only Author')
        self.assertFalse(Author.objects.filter(name='Preview Only Author').exists())

    def test_author_search(self):
        Author.objects.create(name='Existing But Hidden', is_active=False)
        response = self.client.get(reverse('articles:manage_author_search'), {'q': 'existing'})
        self.assertEqual([r['name'] for r in response.json()['results']], ['Dr. Existing Writer'])
        response = self.client.get(reverse('articles:manage_author_search'), {'q': 'teaching'})
        self.assertEqual(response.json()['results'][0]['affiliation'], 'TU Teaching Hospital')
        self.client.logout()
        self.assertNotEqual(self.client.get(reverse('articles:manage_author_search'), {'q': 'x'}).status_code, 200)

    def test_old_authors_page_redirects_to_the_form(self):
        self._create([])
        article = Article.objects.get()
        response = self.client.get(reverse('articles:manage_article_authors', args=[article.slug]))
        self.assertRedirects(response, reverse('articles:manage_article_update', args=[article.slug]) + '#authors',
                             fetch_redirect_response=False)

    def test_form_page_renders_the_authors_box(self):
        response = self.client.get(reverse('articles:manage_article_create'))
        self.assertContains(response, 'id="byline-search"')
        self.assertContains(response, 'name="bylines"')


class AuthorManagementTests(TestCase):
    """/manage/authors/ — byline profiles, no password anywhere."""

    def setUp(self):
        from users.models import User

        self.editor = User.objects.create_user(
            email='author-admin@example.com', password='pw', first_name='A', last_name='E', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='just-reader@example.com', password='pw', first_name='R', last_name='D')

    def test_editor_creates_author_with_name_only(self):
        self.client.force_login(self.editor)
        form_page = self.client.get(reverse('articles:manage_author_create'))
        self.assertFalse([name for name in form_page.context['form'].fields if 'password' in name])
        self.assertNotContains(form_page, 'name="password')
        response = self.client.post(reverse('articles:manage_author_create'), {'name': 'Hari Bahadur', 'is_active': 'on'})
        self.assertRedirects(response, reverse('articles:manage_author_list'))
        author = Author.objects.get(name='Hari Bahadur')
        self.assertIsNone(author.user)
        self.assertEqual(author.slug, 'hari-bahadur')

    def test_non_editor_cannot_manage_authors(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse('articles:manage_author_list')).status_code, 403)

    def test_link_and_unlink_existing_account(self):
        author = Author.objects.create(name='Linkable')
        self.client.force_login(self.editor)
        self.client.post(reverse('articles:manage_author_link_account', args=[author.pk]), {'user': self.reader.pk})
        author.refresh_from_db()
        self.assertEqual(author.user, self.reader)
        self.client.post(reverse('articles:manage_author_link_account', args=[author.pk]), {'user': ''})
        author.refresh_from_db()
        self.assertIsNone(author.user)

    def test_an_account_backs_at_most_one_author(self):
        Author.objects.create(name='First', user=self.reader)
        second = Author.objects.create(name='Second')
        self.client.force_login(self.editor)
        self.client.post(reverse('articles:manage_author_link_account', args=[second.pk]), {'user': self.reader.pk})
        second.refresh_from_db()
        self.assertIsNone(second.user)

    def test_deactivate_keeps_bylines(self):
        article = make_article('kept-byline', Article.ArticleType.NEWS_COMMENTARY)
        author = Author.objects.create(name='Retiring Writer')
        ArticleAuthor.objects.create(article=article, author=author)
        self.client.force_login(self.editor)
        self.client.post(reverse('articles:manage_author_toggle_active', args=[author.pk]))
        author.refresh_from_db()
        self.assertFalse(author.is_active)
        self.assertTrue(article.articleauthor_set.filter(author=author).exists())

    def test_create_author_profile_from_account(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('articles:manage_author_from_account', args=[self.reader.pk]))
        self.assertEqual(self.reader.author_profile.name, 'R D')


class HomepageRoutingTests(TestCase):
    def test_root_serves_homepage(self):
        self.assertEqual(reverse('articles:home'), '/')
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'home.html')

    def test_old_index_url_redirects_permanently(self):
        response = self.client.get('/index/')
        self.assertRedirects(response, '/', status_code=301)


class ArticleEditorSavingTests(TestCase):
    """Single-page article editor: Save draft needs only a title, Publish
    needs the full set, live articles get Update/Unpublish, and autosave
    never touches a live article."""

    def setUp(self):
        from users.models import User

        self.editor = User.objects.create_user(
            email='editor-saving@example.com', password='pw', first_name='E', last_name='S', role=User.Role.EDITOR,
        )
        grant_publish(self.editor)
        self.client.force_login(self.editor)

    def _post_create(self, **data):
        return self.client.post(reverse('articles:manage_article_create'), data)

    def test_draft_saves_with_only_a_title(self):
        response = self._post_create(title='Just A Headline', action='draft')
        self.assertEqual(response.status_code, 302)
        article = Article.objects.get(title='Just A Headline')
        self.assertEqual(article.status, Article.Status.DRAFT)
        self.assertEqual(article.article_type, Article.ArticleType.NEWS_COMMENTARY)

    def test_draft_without_title_is_rejected(self):
        response = self._post_create(title='', abstract='Some notes', action='draft')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Article.objects.exists())

    def test_publish_requires_article_text(self):
        response = self._post_create(
            title='Empty Story', article_type='news_commentary', access_type='open_access', action='publish',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('html_content', response.context['form'].errors)
        self.assertFalse(Article.objects.exists())

    def test_publish_with_text_goes_live(self):
        self._post_create(
            title='Real Story', article_type='news_commentary', access_type='open_access',
            html_content='<p>Clinics reopened.</p>', action='publish',
        )
        self.assertEqual(Article.objects.get(title='Real Story').status, Article.Status.PUBLISHED)

    def test_live_article_shows_update_and_unpublish_not_save_draft(self):
        article = Article.objects.create(
            title='Live One', slug='live-one', status=Article.Status.PUBLISHED, html_content='<p>x</p>',
        )
        response = self.client.get(reverse('articles:manage_article_update', args=[article.slug]))
        self.assertContains(response, 'Update live article')
        self.assertContains(response, 'Unpublish')
        self.assertNotContains(response, 'id="save-draft-btn"')
        self.assertContains(response, 'data-autosave="off"')

    def test_unpublish_moves_live_article_back_to_draft(self):
        article = Article.objects.create(
            title='Live Two', slug='live-two', status=Article.Status.PUBLISHED, html_content='<p>x</p>',
        )
        self.client.post(reverse('articles:manage_article_update', args=[article.slug]), {
            'title': 'Live Two', 'slug': 'live-two', 'article_type': 'news_commentary',
            'access_type': 'open_access', 'html_content': '<p>x</p>', 'action': 'draft',
        })
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.DRAFT)

    def test_autosave_refuses_live_article(self):
        article = Article.objects.create(
            title='Live Three', slug='live-three', status=Article.Status.PUBLISHED, html_content='<p>original</p>',
        )
        response = self.client.post(reverse('articles:manage_article_autosave'), {
            'article_pk': article.pk, 'title': 'Half-typed edit', 'html_content': '<p>oops</p>',
            'article_type': 'news_commentary', 'access_type': 'open_access',
        })
        self.assertEqual(response.status_code, 409)
        article.refresh_from_db()
        self.assertEqual(article.title, 'Live Three')

    def test_autosave_needs_a_title(self):
        response = self.client.post(reverse('articles:manage_article_autosave'), {'title': '  '})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Article.objects.exists())

    def test_single_page_with_required_markers(self):
        response = self.client.get(reverse('articles:manage_article_create'))
        content = response.content.decode()
        self.assertNotIn('Next →', content)
        self.assertIn('id="save-draft-btn"', content)
        self.assertIn('Publish</button>', content)
        # Title is required → marked; the (optional) summary is not.
        title_label = content[content.index('for="id_title"'):content.index('</label>', content.index('for="id_title"'))]
        abstract_label = content[content.index('for="id_abstract"'):content.index('</label>', content.index('for="id_abstract"'))]
        self.assertIn('*</span>', title_label)
        self.assertNotIn('*</span>', abstract_label)


class SchedulingAndTimestampTests(TestCase):
    """Scheduled publishing, real publish times and the "Updated" label."""

    def setUp(self):
        from users.models import User

        self.editor = User.objects.create_user(
            email='scheduler@example.com', password='pw', first_name='S', last_name='E', role=User.Role.EDITOR,
        )
        grant_publish(self.editor)
        self.client.force_login(self.editor)

    def _form(self, **extra):
        data = {
            'title': 'Morning Briefing', 'article_type': 'news_commentary', 'access_type': 'open_access',
            'html_content': '<p>Today in health.</p>',
        }
        data.update(extra)
        return data

    def test_schedule_keeps_article_off_the_site_until_its_time(self):
        when = timezone.localtime() + datetime.timedelta(hours=3)
        response = self.client.post(reverse('articles:manage_article_create'), self._form(
            action='schedule', schedule_at=when.strftime('%Y-%m-%dT%H:%M'),
        ))
        self.assertEqual(response.status_code, 302)
        article = Article.objects.get(title='Morning Briefing')
        self.assertEqual(article.status, Article.Status.SCHEDULED)
        self.assertEqual(timezone.localtime(article.published_at).strftime('%H:%M'), when.strftime('%H:%M'))
        self.assertIsNone(article.publication_date)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('articles:article_detail', args=[article.slug])).status_code, 404)

    def test_schedule_in_the_past_is_rejected(self):
        when = timezone.localtime() - datetime.timedelta(hours=1)
        response = self.client.post(reverse('articles:manage_article_create'), self._form(
            action='schedule', schedule_at=when.strftime('%Y-%m-%dT%H:%M'),
        ))
        self.assertEqual(response.status_code, 200)
        self.assertIn('schedule_at', response.context['form'].errors)

    def test_publish_due_articles_publishes_only_due_ones(self):
        from .tasks import publish_due_articles

        due = Article.objects.create(
            title='Due', slug='due-story', status=Article.Status.SCHEDULED, html_content='<p>x</p>',
            published_at=timezone.now() - datetime.timedelta(minutes=2),
        )
        later = Article.objects.create(
            title='Later', slug='later-story', status=Article.Status.SCHEDULED, html_content='<p>x</p>',
            published_at=timezone.now() + datetime.timedelta(hours=2),
        )
        self.assertEqual(publish_due_articles(), 1)
        due.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual(due.status, Article.Status.PUBLISHED)
        self.assertEqual(due.publication_date, timezone.localdate(due.published_at))
        self.assertEqual(later.status, Article.Status.SCHEDULED)

    def test_publish_now_on_a_scheduled_article_uses_the_current_time(self):
        article = Article.objects.create(
            title='Early', slug='early-story', status=Article.Status.SCHEDULED, html_content='<p>x</p>',
            published_at=timezone.now() + datetime.timedelta(days=1),
        )
        self.client.post(reverse('articles:manage_article_update', args=[article.slug]), self._form(
            title='Early', slug='early-story', action='publish',
        ))
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.PUBLISHED)
        self.assertLessEqual(article.published_at, timezone.now())

    def test_update_live_article_shows_updated_label(self):
        article = Article.objects.create(
            title='Live Story', slug='live-story', status=Article.Status.PUBLISHED, html_content='<p>x</p>',
        )
        self.assertIsNone(article.last_updated_at)
        self.client.post(reverse('articles:manage_article_update', args=[article.slug]), self._form(
            title='Live Story (corrected)', slug='live-story', action='publish',
        ))
        article.refresh_from_db()
        self.assertIsNotNone(article.last_updated_at)
        page = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(page, 'Updated')

    def test_quick_publish_refuses_article_without_text(self):
        article = Article.objects.create(title='Empty', slug='empty-story', status=Article.Status.DRAFT)
        self.client.post(reverse('articles:manage_article_quick_publish', args=[article.slug]))
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.DRAFT)

    def test_news_time_filter(self):
        from .templatetags.news_time import news_time

        now = timezone.now()
        self.assertEqual(news_time(now), 'Just now')
        self.assertEqual(news_time(now - datetime.timedelta(minutes=12)), '12 min ago')
        self.assertEqual(news_time(now - datetime.timedelta(hours=3)), '3 hours ago')
        self.assertEqual(news_time(now - datetime.timedelta(hours=1, minutes=5)), '1 hour ago')
        self.assertNotIn('ago', news_time(now - datetime.timedelta(days=3)))
        self.assertEqual(news_time(None), '')


class CorrectionsAndImageCreditTests(TestCase):
    def setUp(self):
        from users.models import User

        self.editor = User.objects.create_user(
            email='corrections@example.com', password='pw', first_name='C', last_name='E', role=User.Role.EDITOR,
        )
        grant_publish(self.editor)
        self.reader = User.objects.create_user(email='reader-corr@example.com', password='pw', first_name='R', last_name='D')
        self.article = Article.objects.create(
            title='Clinic Opens', slug='clinic-opens', status=Article.Status.PUBLISHED,
            html_content='<p>The clinic opened in 2019.</p>',
            featured_image='articles/images/test.jpg', featured_image_alt='Nurses outside the new clinic',
            featured_image_caption='The clinic on opening day.', featured_image_credit='Ram Shrestha',
        )

    def test_caption_credit_and_alt_on_article_page(self):
        page = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertContains(page, 'alt="Nurses outside the new clinic"')
        self.assertContains(page, 'The clinic on opening day.')
        self.assertContains(page, 'Photo: Ram Shrestha')

    def test_editor_adds_correction_shown_to_readers_and_marks_updated(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('articles:manage_article_correction_add', args=[self.article.slug]), {
            'kind': 'correction', 'note': 'An earlier version said 2019. The clinic opened in 2021.',
        })
        self.article.refresh_from_db()
        self.assertIsNotNone(self.article.last_updated_at)
        correction = self.article.corrections.get()
        self.assertEqual(correction.created_by, self.editor)
        self.client.logout()
        page = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertContains(page, 'id="corrections"')
        self.assertContains(page, 'The clinic opened in 2021.')
        self.assertContains(page, 'Correction appended')
        self.assertContains(page, '"@type": "CorrectionComment"')

    def test_empty_note_is_rejected(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('articles:manage_article_correction_add', args=[self.article.slug]), {'kind': 'update', 'note': ''})
        self.assertFalse(self.article.corrections.exists())

    def test_editor_can_remove_a_note(self):
        from .models import ArticleCorrection

        correction = ArticleCorrection.objects.create(article=self.article, note='Typo in note')
        self.client.force_login(self.editor)
        self.client.post(reverse('articles:manage_article_correction_delete', args=[correction.pk]))
        self.assertFalse(self.article.corrections.exists())

    def test_readers_cannot_add_corrections(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('articles:manage_article_correction_add', args=[self.article.slug]), {
            'kind': 'correction', 'note': 'Sneaky',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.article.corrections.exists())


class ReviewWorkflowAndHistoryTests(TestCase):
    """Draft → In review → Ready → Publish, assignee emails, internal notes,
    revision history/restore, and refusing to overwrite someone's newer save."""

    def setUp(self):
        from django.core import mail  # noqa: F401 — outbox reset per test
        from users.models import User

        self.writer = User.objects.create_user(
            email='writer@example.com', password='pw', first_name='Wri', last_name='Ter', role=User.Role.EDITOR,
        )
        self.chief = User.objects.create_user(
            email='chief@example.com', password='pw', first_name='Chi', last_name='Ef', role=User.Role.EDITOR_IN_CHIEF,
        )
        self.client.force_login(self.writer)

    def _data(self, article=None, **extra):
        data = {
            'title': 'Flu Season Guide', 'article_type': 'news_commentary', 'access_type': 'open_access',
            'html_content': '<p>Get vaccinated.</p>',
        }
        if article:
            from .forms import edit_token_for

            data.update({'slug': article.slug, 'edit_token': edit_token_for(article)})
        data.update(extra)
        return data

    def _create(self, **extra):
        self.client.post(reverse('articles:manage_article_create'), self._data(**extra))
        return Article.objects.get(title=extra.get('title', 'Flu Season Guide'))

    def _update(self, article, **extra):
        return self.client.post(reverse('articles:manage_article_update', args=[article.slug]), self._data(article, **extra))

    def test_full_workflow_and_history(self):
        from django.core import mail

        from .models import ArticleRevision

        article = self._create(action='review', assigned_to=self.chief.pk)
        self.assertEqual(article.status, Article.Status.IN_REVIEW)
        # (setUp's user creation also emails senior staff a verification alert — ignored here.)
        review_mail = [m for m in mail.outbox if m.to == ['chief@example.com'] and 'Flu Season Guide' in m.subject]
        self.assertEqual(len(review_mail), 1)
        self.assertIn('Review requested', review_mail[0].subject)

        self.client.force_login(self.chief)
        self._update(article, action='ready', assigned_to=self.chief.pk)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.READY)
        self._update(article, action='publish', assigned_to=self.chief.pk)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.PUBLISHED)

        actions = list(article.revisions.values_list('action', flat=True))
        self.assertEqual(actions, [ArticleRevision.Action.PUBLISHED, ArticleRevision.Action.APPROVED, ArticleRevision.Action.SUBMITTED])
        self.assertEqual(article.revisions.first().user, self.chief)

    def test_save_in_review_keeps_status_and_needs_only_title(self):
        article = self._create(action='review')
        self._update(article, action='save', html_content='')
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.IN_REVIEW)

    def test_mark_ready_requires_publishable_article(self):
        article = self._create(action='review', html_content='')
        response = self._update(article, action='ready', html_content='')
        self.assertEqual(response.status_code, 200)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.IN_REVIEW)

    def test_no_email_for_assigning_yourself(self):
        from django.core import mail

        self._create(action='review', assigned_to=self.writer.pk)
        self.assertFalse([m for m in mail.outbox if 'Flu Season Guide' in m.subject])

    def test_stale_save_is_refused_instead_of_overwriting(self):
        article = self._create(action='draft')
        from .forms import edit_token_for

        stale_token = edit_token_for(article)
        # The chief saves a newer version first...
        self.client.force_login(self.chief)
        self._update(article, action='save', title='Flu Season Guide (chief edit)')
        # ...then the writer saves from the tab they opened earlier.
        self.client.force_login(self.writer)
        response = self.client.post(
            reverse('articles:manage_article_update', args=[article.slug]),
            self._data(article, action='draft', title='Writer version', edit_token=stale_token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'after you opened it')
        article.refresh_from_db()
        self.assertEqual(article.title, 'Flu Season Guide (chief edit)')

    def test_autosave_coalesces_into_one_history_entry(self):
        from .models import ArticleRevision

        article = self._create(action='draft')
        from .forms import edit_token_for

        for n in range(3):
            response = self.client.post(reverse('articles:manage_article_autosave'), {
                'article_pk': article.pk, 'title': f'Flu Season Guide v{n}', 'article_type': 'news_commentary',
                'access_type': 'open_access', 'edit_token': edit_token_for(Article.objects.get(pk=article.pk)),
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn('edit_token', response.json())
        self.assertEqual(article.revisions.filter(action=ArticleRevision.Action.AUTOSAVED).count(), 1)
        self.assertEqual(article.revisions.first().title, 'Flu Season Guide v2')

    def test_history_shows_word_diff_and_restore_brings_back_old_words(self):
        article = self._create(action='draft', html_content='<p>The clinic opened in 2019.</p>')
        self._update(Article.objects.get(pk=article.pk), action='draft', html_content='<p>The clinic opened in 2021.</p>')
        history = self.client.get(reverse('articles:manage_article_history', args=[article.slug]))
        self.assertContains(history, '<del>2019.</del>')
        self.assertContains(history, '<ins>2021.</ins>')
        first = article.revisions.last()
        self.client.post(reverse('articles:manage_article_revision_restore', args=[first.pk]))
        article.refresh_from_db()
        self.assertIn('2019', article.html_content)
        self.assertEqual(article.revisions.first().action, 'restored')

    def test_internal_notes_are_not_public(self):
        grant_publish(self.writer)
        article = self._create(action='publish')
        self.client.post(reverse('articles:manage_article_note_add', args=[article.slug]), {'body': 'Check the vaccine stock figure.'})
        self.assertEqual(article.notes.get().author, self.writer)
        self.client.logout()
        page = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertNotContains(page, 'Check the vaccine stock figure.')

    def test_only_author_or_senior_staff_delete_notes(self):
        from users.models import User

        other = User.objects.create_user(
            email='other-ed@example.com', password='pw', first_name='O', last_name='E', role=User.Role.EDITOR,
        )
        article = self._create(action='draft')
        self.client.post(reverse('articles:manage_article_note_add', args=[article.slug]), {'body': 'Mine'})
        note = article.notes.get()
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse('articles:manage_article_note_delete', args=[note.pk])).status_code, 403)
        self.client.force_login(self.chief)
        self.client.post(reverse('articles:manage_article_note_delete', args=[note.pk]))
        self.assertFalse(article.notes.exists())

    def test_review_queue_badge_and_assigned_filter(self):
        article = self._create(action='review', assigned_to=self.chief.pk)
        self.client.force_login(self.chief)
        listing = self.client.get(reverse('articles:manage_article_list'), {'assigned': 'me'})
        self.assertEqual(list(listing.context['articles']), [article])
        self.assertContains(listing, 'Review queue')


class SearchSocialAndBreakingNewsTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        from users.models import User

        cache.clear()
        self.editor = User.objects.create_user(
            email='breaking@example.com', password='pw', first_name='B', last_name='E', role=User.Role.EDITOR,
        )
        grant_publish(self.editor)

    def _live(self, **fields):
        defaults = {'title': 'Flood Warning Issued', 'slug': 'flood-warning', 'status': Article.Status.PUBLISHED,
                    'html_content': '<p>Rivers are rising.</p>', 'abstract': 'Rivers are rising fast.'}
        defaults.update(fields)
        return Article.objects.create(**defaults)

    def test_search_overrides_replace_meta_title_and_description(self):
        article = self._live(seo_title='Flood warning: what to do now', seo_description='Five steps to stay safe.')
        page = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(page, '<meta property="og:title" content="Flood warning: what to do now">')
        self.assertContains(page, 'content="Five steps to stay safe."')
        self.assertContains(page, '<title>Flood warning: what to do now')
        # The on-page headline is unchanged.
        self.assertContains(page, 'Flood Warning Issued')

    def test_without_overrides_meta_falls_back_to_headline_and_summary(self):
        article = self._live()
        page = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(page, '<meta property="og:title" content="Flood Warning Issued">')
        self.assertContains(page, 'content="Rivers are rising fast."')

    def test_breaking_banner_shows_site_wide_while_active(self):
        from django.core.cache import cache

        article = self._live(breaking_until=timezone.now() + datetime.timedelta(hours=2))
        home = self.client.get(reverse('articles:home'))
        self.assertContains(home, 'id="breaking-banner"')
        self.assertContains(home, article.get_absolute_url())
        page = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(page, 'BREAKING')
        # Expired → gone (even with the cached entry still present).
        Article.objects.filter(pk=article.pk).update(breaking_until=timezone.now() - datetime.timedelta(minutes=1))
        cache.clear()
        self.assertNotContains(self.client.get(reverse('articles:home')), 'id="breaking-banner"')

    def test_breaking_draft_does_not_show(self):
        self._live(status=Article.Status.DRAFT, breaking_until=timezone.now() + datetime.timedelta(hours=2))
        self.assertNotContains(self.client.get(reverse('articles:home')), 'id="breaking-banner"')

    def test_editor_sets_and_stops_breaking(self):
        from .forms import edit_token_for

        article = self._live()
        self.client.force_login(self.editor)
        url = reverse('articles:manage_article_update', args=[article.slug])
        base = {'title': article.title, 'slug': article.slug, 'article_type': 'news_commentary',
                'access_type': 'open_access', 'html_content': '<p>Rivers are rising.</p>', 'action': 'publish'}
        self.client.post(url, {**base, 'breaking_hours': '3', 'edit_token': edit_token_for(article)})
        article.refresh_from_db()
        self.assertTrue(article.is_breaking)
        self.assertAlmostEqual(
            (article.breaking_until - timezone.now()).total_seconds(), 3 * 3600, delta=120,
        )
        self.client.post(url, {**base, 'breaking_hours': 'off', 'edit_token': edit_token_for(article)})
        article.refresh_from_db()
        self.assertFalse(article.is_breaking)
        self.assertIsNone(article.breaking_until)


class PublishPermissionTests(TestCase):
    """Only publishers (EiC/Admin, or Editors granted "Can publish") put
    things in front of readers; any editor can write, review and mark ready."""

    def setUp(self):
        from users.models import User

        self.editor = User.objects.create_user(
            email='plain-editor@example.com', password='pw', first_name='P', last_name='E', role=User.Role.EDITOR,
        )
        self.chief = User.objects.create_user(
            email='pub-chief@example.com', password='pw', first_name='C', last_name='H', role=User.Role.EDITOR_IN_CHIEF,
        )
        self.data = {
            'title': 'Heatwave Advice', 'article_type': 'news_commentary', 'access_type': 'open_access',
            'html_content': '<p>Drink water.</p>',
        }

    def test_roles_and_grant(self):
        self.assertFalse(self.editor.can_publish)
        self.assertTrue(self.chief.can_publish)
        grant_publish(self.editor)
        self.assertTrue(self.editor.can_publish)

    def test_plain_editor_cannot_publish_but_can_mark_ready(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('articles:manage_article_create'), {**self.data, 'action': 'publish'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only publishers can publish')
        self.assertFalse(Article.objects.filter(status=Article.Status.PUBLISHED).exists())
        self.client.post(reverse('articles:manage_article_create'), {**self.data, 'action': 'ready'})
        self.assertEqual(Article.objects.get().status, Article.Status.READY)

    def test_marking_ready_emails_publishers(self):
        from django.core import mail

        self.client.force_login(self.editor)
        self.client.post(reverse('articles:manage_article_create'), {**self.data, 'action': 'ready'})
        ready = [m for m in mail.outbox if m.subject.startswith('Ready to publish')]
        self.assertEqual(len(ready), 1)
        self.assertIn('pub-chief@example.com', ready[0].to)
        self.assertNotIn('plain-editor@example.com', ready[0].to)

    def test_plain_editor_cannot_change_or_unpublish_live_article(self):
        from .forms import edit_token_for

        article = Article.objects.create(title='Live', slug='live-perm', status=Article.Status.PUBLISHED, html_content='<p>x</p>')
        self.client.force_login(self.editor)
        url = reverse('articles:manage_article_update', args=[article.slug])
        for action in ('publish', 'draft', 'save'):
            self.client.post(url, {**self.data, 'slug': article.slug, 'title': 'Hacked', 'action': action,
                                   'edit_token': edit_token_for(article)})
        article.refresh_from_db()
        self.assertEqual((article.title, article.status), ('Live', Article.Status.PUBLISHED))
        self.client.post(reverse('articles:manage_article_quick_publish', args=[article.slug]))
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.PUBLISHED)
        self.assertEqual(self.client.post(reverse('articles:manage_article_delete', args=[article.slug])).status_code, 403)
        self.assertEqual(self.client.post(reverse('articles:manage_article_correction_add', args=[article.slug]),
                                          {'kind': 'correction', 'note': 'x'}).status_code, 403)
        page = self.client.get(url)
        self.assertContains(page, 'Only publishers can change it')
        self.assertNotContains(page, 'Update live article')

    def test_publisher_editor_can_publish(self):
        grant_publish(self.editor)
        self.client.force_login(self.editor)
        self.client.post(reverse('articles:manage_article_create'), {**self.data, 'action': 'publish'})
        self.assertEqual(Article.objects.get().status, Article.Status.PUBLISHED)

    def test_staff_screen_grants_and_revokes(self):
        from users.models import User

        self.client.force_login(self.chief)
        url = reverse('users:manage_staff_update', args=[self.editor.pk])
        base = {'first_name': 'P', 'last_name': 'E', 'email': self.editor.email, 'role': User.Role.EDITOR, 'is_active': 'on'}
        self.client.post(url, {**base, 'can_publish': 'on'})
        self.assertTrue(User.objects.get(pk=self.editor.pk).can_publish)
        self.client.post(url, base)
        self.assertFalse(User.objects.get(pk=self.editor.pk).can_publish)


class VideoStoryTests(TestCase):
    """Video stories: a YouTube link on an article (articles/video.py)."""

    WATCH = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

    def setUp(self):
        from users.models import User

        self.editor = User.objects.create_user(
            email='video-editor@example.com', password='pw', first_name='V', last_name='E', role=User.Role.EDITOR,
        )
        grant_publish(self.editor)

    def _story(self, slug='clinic-video', **extra):
        data = {'title': 'Inside a rural clinic', 'slug': slug, 'status': Article.Status.PUBLISHED,
                'access_type': Article.AccessType.OPEN_ACCESS, 'article_type': Article.ArticleType.VIDEO,
                'video_url': self.WATCH, 'published_at': timezone.now()}
        data.update(extra)
        return Article.objects.create(**data)

    def test_any_common_youtube_link_is_understood_and_lookalikes_are_not(self):
        from .video import embed_url, youtube_id

        for url in (self.WATCH, 'https://youtu.be/dQw4w9WgXcQ?t=42', 'youtube.com/shorts/dQw4w9WgXcQ',
                    'https://www.youtube.com/live/dQw4w9WgXcQ?si=abc', 'https://www.youtube.com/embed/dQw4w9WgXcQ'):
            self.assertEqual(youtube_id(url), 'dQw4w9WgXcQ', url)
        self.assertEqual(embed_url('https://youtu.be/dQw4w9WgXcQ?t=1m30s'),
                         'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0&start=90')
        for url in ('https://vimeo.com/123', 'https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ',
                    'https://www.youtube.com/watch?v=short', 'javascript:alert(1)'):
            self.assertEqual(youtube_id(url), '', url)

    def test_editor_publishes_a_video_story_without_body_text(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('articles:manage_article_create'), {
            'title': 'Handwashing explained', 'article_type': 'video', 'access_type': 'open_access',
            'video_url': 'https://youtu.be/dQw4w9WgXcQ', 'action': 'publish',
        })
        self.assertEqual(response.status_code, 302)
        article = Article.objects.get(title='Handwashing explained')
        self.assertEqual(article.status, Article.Status.PUBLISHED)
        self.assertTrue(article.has_video)

    def test_bad_link_and_video_type_without_link_are_rejected(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('articles:manage_article_create'), {
            'title': 'Not YouTube', 'article_type': 'news_commentary', 'access_type': 'open_access',
            'video_url': 'https://vimeo.com/123', 'html_content': '<p>x</p>', 'action': 'publish',
        })
        self.assertIn('video_url', response.context['form'].errors)
        response = self.client.post(reverse('articles:manage_article_create'), {
            'title': 'No link', 'article_type': 'video', 'access_type': 'open_access',
            'html_content': '<p>x</p>', 'action': 'publish',
        })
        self.assertIn('video_url', response.context['form'].errors)
        self.assertFalse(Article.objects.exists())

    def test_article_page_shows_the_player_and_video_metadata(self):
        article = self._story()
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, 'src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0"')
        self.assertContains(response, 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg')  # share image
        self.assertContains(response, '"@type": "VideoObject"')
        self.assertNotContains(response, 'Full text has not been added')

    def test_paywalled_video_shows_a_locked_thumbnail_not_the_player(self):
        article = self._story(access_type=Article.AccessType.PAY_PER_ARTICLE, price=100)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, 'href="#paywall"')
        self.assertContains(response, 'id="paywall"')
        # Nothing on the page may give away the video id (it plays free on YouTube).
        self.assertNotContains(response, 'dQw4w9WgXcQ')
        for url in (reverse('articles:video_list'), reverse('articles:article_list'), '/feed/'):
            self.assertNotContains(self.client.get(url), 'dQw4w9WgXcQ', msg_prefix=url)
        # A subscriber gets the player.
        from users.models import User
        from billing.models import ArticlePurchase

        buyer = User.objects.create_user(email='video-buyer@example.com', password='pw', first_name='B', last_name='U')
        ArticlePurchase.objects.create(user=buyer, article=article, amount=100)
        self.client.force_login(buyer)
        self.assertContains(self.client.get(reverse('articles:article_detail', args=[article.slug])),
                            'youtube-nocookie.com/embed/dQw4w9WgXcQ')

    def test_videos_page_lists_only_published_video_stories(self):
        self._story()
        self._story(slug='draft-video', status=Article.Status.DRAFT, title='Unreleased clip')
        Article.objects.create(title='Plain text story', slug='plain-story', status=Article.Status.PUBLISHED,
                               html_content='<p>x</p>', published_at=timezone.now())
        response = self.client.get(reverse('articles:video_list'))
        self.assertContains(response, 'Inside a rural clinic')
        self.assertNotContains(response, 'Unreleased clip')
        self.assertNotContains(response, 'Plain text story')

    def test_video_shows_on_homepage_and_cards_use_the_youtube_thumbnail(self):
        from django.core.cache import cache

        cache.clear()
        self._story()
        home = self.client.get(reverse('articles:home'))
        self.assertContains(home, reverse('articles:video_list'))
        self.assertContains(home, 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg')
        listing = self.client.get(reverse('articles:article_list'))
        self.assertContains(listing, 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg')

    def test_homepage_showcase_plays_free_videos_inline_but_never_exposes_a_paid_one(self):
        from django.core.cache import cache

        cache.clear()
        # The newest story takes the homepage's lead spot, so give it one that isn't a video.
        Article.objects.create(title='Lead story', slug='lead-story', status=Article.Status.PUBLISHED,
                               html_content='<p>x</p>', published_at=timezone.now())
        self._story(slug='free-clip', title='Free clinic clip', published_at=timezone.now() - datetime.timedelta(minutes=30))
        self._story(slug='paid-clip', title='Paid budget briefing', video_url='https://youtu.be/aqz-KE-bpKQ',
                    access_type=Article.AccessType.SUBSCRIPTION, published_at=timezone.now() - datetime.timedelta(hours=1))
        home = self.client.get(reverse('articles:home'))
        self.assertContains(home, 'data-video-showcase')
        self.assertContains(home, 'data-reel-item ', count=2)
        # The free one carries its player address for inline play...
        self.assertContains(home, 'data-embed="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0"')
        # ...the paid one sends ▶ to its paywall and its id appears nowhere.
        self.assertContains(home, 'Paid budget briefing')
        self.assertNotContains(home, 'aqz-KE-bpKQ')
        self.assertContains(home, f'data-url="{reverse("articles:article_detail", args=["paid-clip"])}"')

    def test_videos_is_in_the_main_menu(self):
        from sections.models import Section

        entry = Section.objects.get(slug='videos')
        self.assertEqual(entry.nav_url, reverse('articles:video_list'))
        self.assertContains(self.client.get(reverse('articles:home')), f'href="{reverse("articles:video_list")}"')
