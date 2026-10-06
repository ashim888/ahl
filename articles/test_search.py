"""Search (articles/search.py): the ngram FULLTEXT index, ranking, filters,
snippets, suggestions and keeping the index current."""
import datetime

from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from sections.models import Section

from . import search
from .models import Article, ArticleAuthor, Author, Keyword


def story(slug, title, body='', **extra):
    data = {'title': title, 'slug': slug, 'status': Article.Status.PUBLISHED, 'html_content': f'<p>{body}</p>' if body else '',
            'access_type': Article.AccessType.OPEN_ACCESS}
    data.update(extra)
    return Article.objects.create(**data)


class FullTextIndexTests(TransactionTestCase):
    """Committed rows, so the real MySQL ngram FULLTEXT index is used."""

    def setUp(self):
        cache.clear()
        self.malaria = story('malaria-jumla', 'Malaria vaccine trial reaches Jumla', 'Health posts in Karnali began the trial.')
        self.body_only = story('karnali-roundup', 'Karnali health roundup', 'A new malaria case was reported near Jumla.')
        self.nepali = story('swasthya-bima', 'स्वास्थ्य बीमा कार्यक्रम विस्तार', 'नेपालमा स्वास्थ्य बीमा २०८२ देखि विस्तार।')
        self.tb = story('tb-cases', 'TB cases rise in the valley', 'Clinics report more TB.')

    def _results(self, query, **params):
        response = self.client.get(reverse('articles:search'), {'q': query, **params})
        return [a.slug for a in response.context['articles']]

    def test_uses_the_index_and_ranks_title_matches_first(self):
        from unittest.mock import patch

        # The FULLTEXT path finds them — the substring fallback is never needed.
        with patch.object(Article.objects, 'filter', wraps=Article.objects.filter):
            ids = search.search_ids(Article.objects.all(), 'malaria')
        self.assertEqual(ids, [self.malaria.pk, self.body_only.pk])
        self.assertEqual(self._results('malaria'), ['malaria-jumla', 'karnali-roundup'])

    def test_article_text_is_searched_not_just_titles(self):
        self.assertEqual(self._results('Karnali posts'), ['malaria-jumla'])

    def test_nepali_short_terms_partial_words_and_digits(self):
        self.assertEqual(self._results('बीमा'), ['swasthya-bima'])
        self.assertEqual(self._results('TB'), ['tb-cases'])
        self.assertEqual(self._results('vacc'), ['malaria-jumla'])
        self.assertEqual(self._results('2082'), ['swasthya-bima'])  # matches २०८२

    def test_suggestions_come_from_the_title_index(self):
        response = self.client.get(reverse('articles:search_suggest'), {'q': 'vaccine'})
        self.assertEqual([r['title'] for r in response.json()['results']], ['Malaria vaccine trial reaches Jumla'])


class SearchFeatureTests(TestCase):
    def setUp(self):
        cache.clear()
        self.section = Section.objects.create(name='Disease Watch', slug='disease-watch-test')
        self.recent = story('recent-dengue', 'Dengue alert in Kathmandu', 'Cases of dengue rose this week.', section=self.section)
        self.old = story('old-dengue', 'Dengue lessons from 2019', 'An older dengue story.',
                         article_type=Article.ArticleType.EDITORIAL)
        Article.objects.filter(pk=self.old.pk).update(published_at=timezone.now() - datetime.timedelta(days=400))

    def _get(self, **params):
        return self.client.get(reverse('articles:search'), params)

    def test_filters(self):
        self.assertEqual([a.slug for a in self._get(q='dengue', section='disease-watch-test').context['articles']], ['recent-dengue'])
        self.assertEqual([a.slug for a in self._get(q='dengue', type='editorial').context['articles']], ['old-dengue'])
        self.assertEqual([a.slug for a in self._get(q='dengue', when='month').context['articles']], ['recent-dengue'])
        self.assertEqual(self._get(q='dengue', sort='newest').context['articles'][0].slug, 'recent-dengue')

    def test_snippets_highlight_matches_but_never_leak_paid_text(self):
        response = self._get(q='rose')
        self.assertContains(response, '<mark>rose</mark>')
        story('paid-dengue', 'Dengue costs', 'SECRET paywalled finding about dengue.',
              access_type=Article.AccessType.SUBSCRIPTION, abstract='Public summary on dengue costs.')
        response = self._get(q='dengue costs')
        self.assertContains(response, 'Public summary on <mark>dengue</mark>')
        self.assertNotContains(response, 'SECRET')

    def test_did_you_mean(self):
        Keyword.objects.create(name='Malaria')
        response = self._get(q='maleria')
        self.assertEqual(response.context['did_you_mean'], 'malaria')
        self.assertContains(response, 'Did you mean')

    def test_drafts_never_appear(self):
        story('draft-dengue', 'Dengue draft', status=Article.Status.DRAFT)
        self.assertNotIn('draft-dengue', [a.slug for a in self._get(q='dengue').context['articles']])
        self.assertEqual(self.client.get(reverse('articles:search_suggest'), {'q': 'draft'}).json()['results'], [])

    def test_results_are_cached_until_something_changes(self):
        self.assertEqual(len(self._get(q='dengue').context['articles']), 2)
        story('new-dengue', 'Dengue vaccine hope')
        self.assertEqual(len(self._get(q='dengue').context['articles']), 3)

    def test_search_text_follows_keywords_authors_and_sections(self):
        keyword = Keyword.objects.create(name='Vector control')
        self.recent.keyword_tags.add(keyword)
        author = Author.objects.create(name='Sita Pokharel')
        ArticleAuthor.objects.create(article=self.recent, author=author, order=0)
        self.recent.refresh_from_db()
        self.assertIn('Vector control', self.recent.search_text)
        self.assertIn('Sita Pokharel', self.recent.search_text)
        author.name = 'Sita K. Pokharel'
        author.save()
        self.section.name = 'Outbreaks'
        self.section.save()
        self.recent.refresh_from_db()
        self.assertIn('Sita K. Pokharel', self.recent.search_text)
        self.assertIn('Outbreaks', self.recent.search_text)

    def test_rebuild_command(self):
        from io import StringIO

        from django.core.management import call_command

        Article.objects.update(search_text='')
        out = StringIO()
        call_command('rebuild_search_index', stdout=out)
        self.assertIn('Rebuilt search text', out.getvalue())
        self.assertTrue(all(Article.objects.values_list('search_text', flat=True)))

    def test_header_search_has_type_ahead(self):
        page = self.client.get(reverse('articles:home'))
        self.assertContains(page, 'data-search-suggest')
        self.assertContains(page, 'js/search_suggest.js')
