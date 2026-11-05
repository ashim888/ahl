"""The article page's evidence trail and reading furniture (article_detail.html):
the source count links to the references, dates lead with Bikram Sambat, d3
loads only for stories with a chart, and editors are warned when references
are never cited in the text."""
import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

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
        self.assertIn('· ', text)

    def test_english_pages_name_the_calendar(self):
        with translation.override('en'):
            self.assertEqual(dual_date(self.moment, 'time'), '15 Kartik 2083 BS (November 1, 2026)\u00a0· 3:48\u00a0PM')
            self.assertEqual(dual_date(self.moment), '15 Kartik 2083 BS (November 1, 2026)')

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
