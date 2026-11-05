"""The article page's evidence trail and reading furniture (article_detail.html):
the source count links to the references, dates lead with Bikram Sambat, d3
loads only for stories with a chart, and editors are warned when references
are never cited in the text."""
import datetime
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from billing.money import format_money

from .citations import uncited_references_warning
from .models import Article
from .templatetags.news_time import dual_date
from .tests import make_article

THREE_SOURCES = 'Smith J. 2024.\nThapa B. 2025.\nWHO fact sheet. 2026.'


class DualDateTests(TestCase):
    def setUp(self):
        self.moment = timezone.make_aware(datetime.datetime(2026, 11, 1, 15, 48))

    def test_nepali_pages_lead_with_bikram_sambat(self):
        with translation.override('ne'):
            text = dual_date(self.moment, 'time')
        self.assertTrue(text.startswith('१५ कात्तिक २०८३ ('), text)
        self.assertIn('२०२६', text)  # the AD date follows, in Devanagari digits
        self.assertIn('\u00a0·\u00a0', text)

    def test_english_pages_name_the_calendar(self):
        with translation.override('en'):
            self.assertEqual(dual_date(self.moment, 'time'), '15 Kartik 2083 BS (November\u00a01,\u00a02026)\u00a0·\u00a03:48\u00a0PM')
            self.assertEqual(dual_date(self.moment), '15 Kartik 2083 BS (November\u00a01,\u00a02026)')

    def test_midnight_is_a_date_only_stamp(self):
        midnight = timezone.make_aware(datetime.datetime(2026, 11, 1, 0, 0))
        with translation.override('en'):
            self.assertNotIn('·', dual_date(midnight, 'time'))

    def test_empty(self):
        self.assertEqual(dual_date(None), '')


class UncitedReferencesWarningTests(TestCase):
    def _article(self, body, references=THREE_SOURCES):
        return Article(title='Dengue in Kathmandu', html_content=body, references=references)

    def test_no_references_no_warning(self):
        self.assertEqual(uncited_references_warning(self._article('<p>Text</p>', references='')), '')

    def test_references_never_cited_warn(self):
        warning = uncited_references_warning(self._article('<p>Cases doubled this year.</p>'))
        self.assertIn('lists 3 sources', warning)
        self.assertIn('[1], [2]', warning)

    def test_one_citation_is_enough(self):
        self.assertEqual(uncited_references_warning(self._article('<p>Cases doubled.[2]</p>')), '')

    def test_brackets_in_code_samples_are_not_citations(self):
        self.assertIn('lists 3 sources', uncited_references_warning(self._article('<pre><code>rows[1]</code></pre>')))


class ArticlePageEvidenceTests(TestCase):
    def setUp(self):
        self.article = make_article('evidence-story', Article.ArticleType.NEWS_COMMENTARY)
        self.article.html_content = '<p>Cases doubled.[1]</p>'
        self.article.references = THREE_SOURCES
        self.article.save()

    def _get(self):
        return self.client.get(reverse('articles:article_detail', args=[self.article.slug]))

    def test_source_count_jumps_to_the_references(self):
        response = self._get()
        self.assertContains(response, '<a href="#references" class="story-flag story-flag--sources story-flag--link">')
        self.assertContains(response, '<section id="references"')
        self.assertContains(response, '(3)</span></h2>')

    def test_cards_keep_the_plain_source_count(self):
        response = self.client.get(reverse('articles:article_list'))
        self.assertNotContains(response, 'story-flag--link')

    def test_byline_without_authors_links_to_the_editorial_board(self):
        self.assertContains(self._get(), f'href="{reverse("editorial_board:public_list")}"')

    def test_d3_only_for_stories_with_a_chart(self):
        self.assertNotContains(self._get(), 'vendor/d3/')
        self.article.html_content = '<div id="c"></div><script>d3.select("#c").append("svg");</script>'
        self.article.save()
        response = self._get()
        self.assertContains(response, 'vendor/d3/d3.v7.9.0.min.js')
        self.assertNotContains(response, '<script src="https://d3js.org')

    def test_copy_feedback_is_announced(self):
        self.assertContains(self._get(), '<p id="copy-status" class="sr-only" role="status" aria-live="polite"></p>')


class ManageArticleUncitedWarningTests(TestCase):
    def test_saving_uncited_references_warns_the_editor(self):
        from users.models import User

        editor = User.objects.create_user(email='refs-editor@example.com', password='pw', first_name='E', last_name='D',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        response = self.client.post(reverse('articles:manage_article_create'), {
            'title': 'Dengue in Kathmandu', 'slug': 'dengue-in-kathmandu', 'abstract': 'x',
            'article_type': Article.ArticleType.NEWS_COMMENTARY, 'access_type': Article.AccessType.OPEN_ACCESS,
            'html_content': '<p>Cases doubled.</p>', 'references': THREE_SOURCES, 'action': 'draft',
        }, follow=True)
        self.assertContains(response, 'the text doesn&#x27;t cite any')


class ReferenceAndImageFilterTests(TestCase):
    def test_bare_doi_links_to_doi_org(self):
        from .templatetags.text_filters import reference_links

        html = reference_links('Thapa B. Stroke in Nepal. 2025. doi:10.1234/ahl.2025.7.')
        self.assertIn('<a href="https://doi.org/10.1234/ahl.2025.7" rel="nofollow">doi:10.1234/ahl.2025.7</a>.', html)

    def test_doi_inside_a_url_is_linked_once(self):
        from .templatetags.text_filters import reference_links

        html = reference_links('See https://doi.org/10.1234/x1')
        self.assertEqual(html.count('<a '), 1)

    def test_headline_as_alt_is_decorative(self):
        from .templatetags.text_filters import image_alt

        self.assertEqual(image_alt(Article(title='Dengue rises', featured_image_alt='Dengue rises')), '')
        self.assertEqual(image_alt(Article(title='Dengue rises', featured_image_alt='Nurses in Jumla')), 'Nurses in Jumla')


class SummaryInBodyTests(TestCase):
    BODY = '<p><strong>संक्षेप</strong></p><p>पहिलो वाक्य।&nbsp;दोस्रो वाक्य यहाँ छ।</p><h2>परिचय</h2><p>…</p>'

    def test_summary_copied_from_the_bodys_abstract(self):
        from .toc import summary_repeated_in_body

        self.assertTrue(summary_repeated_in_body(self.BODY, 'दोस्रो वाक्य यहाँ छ।'))

    def test_reworded_summary_or_no_abstract_section_is_kept(self):
        from .toc import summary_repeated_in_body

        self.assertFalse(summary_repeated_in_body(self.BODY, 'अर्कै सारांश।'))
        self.assertFalse(summary_repeated_in_body('<p><strong>भूमिका</strong></p><p>दोस्रो वाक्य यहाँ छ।</p>', 'दोस्रो वाक्य यहाँ छ।'))

    def test_article_page_shows_it_once(self):
        article = make_article('summary-once', Article.ArticleType.NEWS_COMMENTARY)
        article.abstract = 'दोस्रो वाक्य यहाँ छ।'
        article.html_content = self.BODY
        article.save()
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertTrue(response.context['summary_in_body'])
        # No standfirst under the headline (the summary still feeds the meta description).
        self.assertNotContains(response, 'leading-relaxed text-muted-foreground mb-6" style="font-size: calc(1.25rem')


@patch('billing.access.FREE_SAMPLE_LIMIT_PER_MONTH', 0)  # no free read: the paywall shows
class LockedAndArchivedArticleTests(TestCase):
    BODY = '<h2>Background</h2><p>One.</p><h2>Findings</h2><p>Two.</p><h2>What it means</h2><p>Three.</p>'

    def _article(self, slug, **fields):
        article = make_article(slug, Article.ArticleType.NEWS_COMMENTARY)
        article.html_content = self.BODY
        for name, value in fields.items():
            setattr(article, name, value)
        article.save()
        return article

    def _get(self, article):
        return self.client.get(reverse('articles:article_detail', args=[article.slug]))

    def test_locked_article_lists_sections_without_dead_links(self):
        response = self._get(self._article('locked-sections', access_type=Article.AccessType.SUBSCRIPTION))
        self.assertFalse(response.context['show_full_text'])
        self.assertContains(response, "What's inside")
        self.assertContains(response, '<li>Findings</li>')
        self.assertNotContains(response, 'class="toc-link')

    def test_single_purchase_price_includes_vat_on_label_and_button(self):
        response = self._get(self._article('special-buy', access_type=Article.AccessType.PAY_PER_ARTICLE, price=100))
        self.assertFalse(response.context['show_full_text'])
        self.assertNotContains(response, '+ VAT')
        self.assertContains(response, 'incl. VAT')
        # Rs 100 + 13% VAT, the same total on the price and on the BUY button
        self.assertContains(response, format_money(113), count=2)

    def test_archived_article_can_still_be_cited_and_saved(self):
        from users.models import User

        article = self._article('archived-cite', status=Article.Status.ARCHIVED)
        self.assertEqual(self.client.get(reverse('articles:article_citation', args=[article.slug, 'bibtex'])).status_code, 200)
        reader = User.objects.create_user(email='reader-archive@example.com', password='pw', first_name='R', last_name='D')
        self.client.force_login(reader)
        self.client.post(reverse('articles:article_bookmark_toggle', args=[article.slug]))
        self.assertTrue(reader.bookmarks.filter(article=article).exists())

    def test_progress_bar_sits_above_the_sticky_header(self):
        self.assertContains(self._get(self._article('progress-bar')),
                            'id="reading-progress" class="fixed top-0 left-0 right-0 z-[60]')
