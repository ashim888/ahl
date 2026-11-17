import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from articles.models import Article, Keyword
from users.models import User

from .models import Resource

MEDIA = tempfile.mkdtemp()
PDF = b'%PDF-1.4\n%fake but valid header\n'


def pdf(name='report.pdf', content=PDF):
    return SimpleUploadedFile(name, content, content_type='application/pdf')


def make(title, **kwargs):
    kwargs.setdefault('resource_type', Resource.ResourceType.GOVERNMENT_REPORT)
    kwargs.setdefault('summary', 'A plain-language summary.')
    kwargs.setdefault('external_url', 'https://www.mohp.gov.np/report')
    kwargs.setdefault('is_published', True)
    return Resource.objects.create(title=title, **kwargs)


@override_settings(MEDIA_ROOT=MEDIA)
class LibraryPublicTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.dengue = Keyword.objects.create(name='Dengue', slug='dengue')
        self.report = make('Annual Health Report 2080/81', source='Ministry of Health and Population', year=2024,
                           language=Resource.Language.NEPALI)
        self.report.keyword_tags.add(self.dengue)
        self.guideline = make('Dengue Clinical Guideline', resource_type=Resource.ResourceType.GUIDELINE,
                              language=Resource.Language.BOTH, external_url='', file=pdf())
        self.hidden = make('Draft resource', is_published=False)

    def titles(self, **params):
        response = self.client.get(reverse('library:resource_list'), params)
        self.assertEqual(response.status_code, 200)
        return [r.title for r in response.context['resources']]

    def test_list_shows_only_published(self):
        self.assertCountEqual(self.titles(), [self.report.title, self.guideline.title])

    def test_filters(self):
        self.assertEqual(self.titles(type='guideline'), [self.guideline.title])
        self.assertEqual(self.titles(topic='dengue'), [self.report.title])
        self.assertEqual(self.titles(q='ministry'), [self.report.title])
        # A bilingual resource shows under English and Nepali.
        self.assertEqual(self.titles(lang='en'), [self.guideline.title])
        self.assertCountEqual(self.titles(lang='ne'), [self.report.title, self.guideline.title])
        self.assertCountEqual(self.titles(type='nonsense'), [self.report.title, self.guideline.title])

    def test_search_matches_topics(self):
        self.assertIn(self.report.title, self.titles(q='Dengue'))

    def test_long_search_stays_one_query_without_duplicates(self):
        from articles.models import Keyword

        from .queries import matching, published

        many = make('Many topics guide')
        many.keyword_tags.set([Keyword.objects.create(name=f'Malaria {i}', slug=f'malaria-{i}') for i in range(6)])
        with self.assertNumQueries(1):  # a join per word used to multiply rows: topics ^ words
            found = list(matching(published(), ' '.join(['malaria'] * 12)))
        self.assertEqual(found, [many])  # six matching topics, listed once

    def test_detail_and_unpublished_404(self):
        response = self.client.get(self.report.get_absolute_url())
        self.assertContains(response, 'Annual Health Report')
        self.assertContains(response, 'mohp.gov.np')
        self.assertEqual(self.client.get(self.hidden.get_absolute_url()).status_code, 404)

    def test_download_counts_and_redirects(self):
        response = self.client.get(reverse('library:resource_download', args=[self.report.slug]))
        self.assertRedirects(response, 'https://www.mohp.gov.np/report', fetch_redirect_response=False)
        response = self.client.get(reverse('library:resource_download', args=[self.guideline.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].endswith('.pdf'))
        self.report.refresh_from_db()
        self.assertEqual(self.report.download_count, 1)
        self.assertEqual(self.client.get(reverse('library:resource_download', args=[self.hidden.slug])).status_code, 404)

    def test_file_details_recorded(self):
        self.assertEqual(self.guideline.file_format, 'PDF')
        self.assertEqual(self.guideline.file_size, len(PDF))
        self.assertEqual(self.report.link_host, 'mohp.gov.np')

    def test_slug_from_title_and_unique(self):
        self.assertEqual(self.guideline.slug, 'dengue-clinical-guideline')
        self.assertEqual(make('Dengue Clinical Guideline').slug, 'dengue-clinical-guideline-2')

    def test_admin_rejects_a_non_ascii_slug(self):
        # A Nepali slug can't be routed by <slug:slug>, so every page linking to it
        # would crash; the admin form has to refuse it.
        # (Admin builds its slug input from this same model field.)
        from django.core.exceptions import ValidationError

        slug_input = Resource._meta.get_field('slug').formfield()
        with self.assertRaises(ValidationError):
            slug_input.clean('वार्षिक-प्रतिवेदन')
        self.assertEqual(slug_input.clean('annual-report'), 'annual-report')

    def test_in_sitemap(self):
        response = self.client.get('/sitemap.xml')
        if response.status_code == 200 and b'sitemap-library' in response.content:
            response = self.client.get('/sitemap-library.xml')
        self.assertContains(response, self.report.slug)


@override_settings(MEDIA_ROOT=MEDIA)
class LibraryManageTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(email='ed@example.com', password='pw', first_name='E', last_name='D',
                                               role=User.Role.EDITOR)
        self.client.force_login(self.editor)
        self.url = reverse('library:manage_resource_create')

    def data(self, **extra):
        data = {'title': 'National Nutrition Survey', 'resource_type': 'dataset', 'summary': 'Survey results.',
                'source': 'NHRC', 'year': '2023', 'language': 'en', 'is_published': 'on'}
        data.update(extra)
        return data

    def test_readers_refused(self):
        reader = User.objects.create_user(email='r@example.com', password='pw', first_name='R', last_name='D')
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('library:manage_resource_list')).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_create_with_link_topics_and_related(self):
        article = Article.objects.create(title='Nutrition story', status=Article.Status.PUBLISHED)
        response = self.client.post(self.url, self.data(
            external_url='https://nhrc.gov.np/survey',
            keywords=json.dumps([{'value': 'Nutrition'}]),
            related=json.dumps([{'value': article.title, 'id': article.pk}]),
        ))
        self.assertRedirects(response, reverse('library:manage_resource_list'))
        resource = Resource.objects.get()
        self.assertEqual(resource.created_by, self.editor)
        self.assertEqual([k.name for k in resource.keyword_tags.all()], ['Nutrition'])
        self.assertEqual(list(resource.related_articles.all()), [article])

    def test_create_with_file(self):
        self.client.post(self.url, self.data(file=pdf('survey.pdf')))
        self.assertTrue(Resource.objects.get().file.name.endswith('.pdf'))

    def test_needs_exactly_one_of_file_or_link(self):
        response = self.client.post(self.url, self.data())
        self.assertContains(response, 'Upload a file or give a link')
        response = self.client.post(self.url, self.data(file=pdf(), external_url='https://nhrc.gov.np/x'))
        self.assertContains(response, 'not both')
        self.assertFalse(Resource.objects.exists())

    def test_rejects_disguised_and_unsupported_files(self):
        response = self.client.post(self.url, self.data(file=pdf('evil.pdf', b'<html>not a pdf</html>')))
        self.assertContains(response, "doesn&#x27;t look like a real PDF")
        response = self.client.post(self.url, self.data(file=SimpleUploadedFile('tool.exe', b'MZ...')))
        self.assertFalse(Resource.objects.exists())
        self.assertEqual(response.status_code, 200)

    def test_csv_accepted_binary_csv_rejected(self):
        self.client.post(self.url, self.data(file=SimpleUploadedFile('data.csv', b'district,cases\nKathmandu,40\n')))
        self.assertEqual(Resource.objects.count(), 1)
        response = self.client.post(self.url, self.data(title='Other', file=SimpleUploadedFile('bad.csv', b'a\x00b')))
        self.assertContains(response, 'binary data')

    def test_edit_and_delete(self):
        resource = make('Old title')
        self.client.post(reverse('library:manage_resource_update', args=[resource.pk]),
                         self.data(title='New title', external_url=resource.external_url))
        resource.refresh_from_db()
        self.assertEqual(resource.title, 'New title')
        self.assertEqual(resource.slug, 'old-title')  # the address doesn't change on edit
        self.client.post(reverse('library:manage_resource_delete', args=[resource.pk]))
        self.assertFalse(Resource.objects.exists())

    def test_manage_list(self):
        make('Listed resource', is_published=False)
        self.assertContains(self.client.get(reverse('library:manage_resource_list')), 'Listed resource')


class GlossaryTests(TestCase):
    def setUp(self):
        from .models import GlossaryTerm

        self.diabetes = GlossaryTerm.objects.create(
            term_ne='मधुमेह', term_en='Diabetes', also_called='Sugar disease, DM',
            definition_ne='रगतमा चिनीको मात्रा लामो समयसम्म धेरै भइरहने रोग।',
            definition_en='A long-term condition where blood sugar stays too high.', is_published=True)
        self.hba1c = GlossaryTerm.objects.create(term_en='HbA1c', definition_en='A blood test of average sugar.',
                                                 is_published=True)
        self.hba1c.related_terms.add(self.diabetes)
        self.draft = GlossaryTerm.objects.create(term_en='Draft term', definition_en='Not ready.')
        self.editor = User.objects.create_user(email='g@example.com', password='pw', first_name='G', last_name='E',
                                               role=User.Role.EDITOR)

    def test_names_and_slug(self):
        self.assertEqual(self.diabetes.display_name, 'मधुमेह (Diabetes)')
        self.assertEqual(self.diabetes.slug, 'diabetes')
        self.assertEqual(self.diabetes.names, ['मधुमेह', 'Diabetes', 'Sugar disease', 'DM'])
        self.assertEqual(self.hba1c.index_letter, 'H')
        self.assertEqual(self.diabetes.index_letter, 'म')

    def test_list_groups_by_letter_and_hides_drafts(self):
        response = self.client.get(reverse('library:glossary_list'))
        groups = dict(response.context['groups'])
        self.assertEqual(list(groups), ['म', 'H'])  # Devanagari first
        self.assertNotContains(response, 'Draft term')

    def found(self, query):
        groups = self.client.get(reverse('library:glossary_list'), {'q': query}).context['groups']
        return [term for _, terms in groups for term in terms]

    def test_search_by_alias_and_definition(self):
        self.assertEqual(self.found('sugar disease'), [self.diabetes])
        self.assertEqual(self.found('average'), [self.hba1c])
        self.assertEqual(self.found('मधुमेह'), [self.diabetes])

    def test_detail_page(self):
        response = self.client.get(self.diabetes.get_absolute_url())
        self.assertContains(response, 'रगतमा चिनीको')
        self.assertContains(response, 'HbA1c')  # related, symmetrical
        self.assertContains(response, '"@type": "DefinedTerm"')
        self.assertNotContains(self.client.get(self.hba1c.get_absolute_url()), 'alternateName')  # no other names
        self.assertEqual(self.client.get(self.draft.get_absolute_url()).status_code, 404)

    def test_json_ld_cannot_close_the_script_tag(self):
        self.diabetes.definition_ne = 'Bad </script><script>alert(1)</script>'
        self.diabetes.save()
        response = self.client.get(self.diabetes.get_absolute_url())
        self.assertNotContains(response, '</script><script>alert(1)')

    def test_site_search_shows_matching_term(self):
        response = self.client.get(reverse('articles:search'), {'q': 'मधुमेह'})
        self.assertEqual(response.context['glossary_terms'], [self.diabetes])
        response = self.client.get(reverse('articles:search'), {'q': 'average'})
        self.assertEqual(response.context['glossary_terms'], [])  # names only, not definitions

    def test_glossary_slug_reserved_for_documents(self):
        self.assertEqual(make('Glossary').slug, 'glossary-document')
        self.assertEqual(self.client.get('/library/glossary/').status_code, 200)

    def test_editor_create_and_duplicate_check(self):
        self.client.force_login(self.editor)
        url = reverse('library:manage_glossary_create')
        response = self.client.post(url, {'term_ne': 'उच्च रक्तचाप', 'term_en': 'Hypertension',
                                          'definition_ne': 'रगतको चाप लगातार बढी हुनु।', 'is_published': 'on',
                                          'keywords': json.dumps([{'value': 'Heart'}])})
        self.assertRedirects(response, reverse('library:manage_glossary_list'))
        from .models import GlossaryTerm

        term = GlossaryTerm.objects.get(term_en='Hypertension')
        self.assertEqual(term.created_by, self.editor)
        self.assertEqual([k.name for k in term.keyword_tags.all()], ['Heart'])
        response = self.client.post(url, {'term_en': 'diabetes', 'definition_en': 'Again.'})
        self.assertContains(response, 'already a name of')
        # "Other names" count too, both ways: DM is already Diabetes's alias.
        response = self.client.post(url, {'term_en': 'DM', 'definition_en': 'Again.'})
        self.assertContains(response, 'already a name of')
        response = self.client.post(url, {'term_en': 'Glucose', 'also_called': 'HBA1C', 'definition_en': 'x'})
        self.assertContains(response, 'already a name of')
        response = self.client.post(url, {'term_en': 'Something'})
        self.assertContains(response, 'Write a definition')

    def test_readers_refused(self):
        reader = User.objects.create_user(email='rr@example.com', password='pw', first_name='R', last_name='R')
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('library:manage_glossary_list')).status_code, 403)


class GlossaryMarkingTests(TestCase):
    """Glossary terms marked in article text (glossary_marking.py)."""

    def setUp(self):
        from .glossary_marking import clear_cache
        from .models import GlossaryTerm

        clear_cache()  # test rollbacks don't send post_delete, so start clean
        self.diabetes = GlossaryTerm.objects.create(
            term_ne='मधुमेह', term_en='Diabetes', also_called='DM',
            definition_ne='रगतमा चिनी धेरै हुने रोग।', definition_en='High blood sugar.', is_published=True)
        self.vaccine = GlossaryTerm.objects.create(term_ne='खोप', term_en='Vaccine',
                                                   definition_ne='रोगबाट जोगाउने औषधि।', is_published=True)
        self.who = GlossaryTerm.objects.create(term_en='WHO', definition_en='World Health Organization.',
                                               is_published=True)
        GlossaryTerm.objects.create(term_en='Hidden', definition_en='Draft.')

    def mark(self, html, **kwargs):
        from .glossary_marking import mark_terms

        return mark_terms(html, **kwargs)

    def test_nepali_with_endings_marked_once(self):
        html, used = self.mark('<p>मधुमेहको उपचार। मधुमेह फेरि।</p><p>खोपहरू लगाउनुहोस्।</p>')
        self.assertEqual(used, ['diabetes', 'vaccine'])
        self.assertIn('<a href="/library/glossary/diabetes/" class="glossary-term" data-glossary="diabetes">मधुमेह</a>को', html)
        self.assertEqual(html.count('glossary-term'), 2)  # second मधुमेह left alone
        self.assertIn('>खोप</a>हरू', html)

    def test_nepali_term_at_end_of_sentence_or_before_digits(self):
        html, used = self.mark('<p>यो रोग मधुमेह। सबैलाई खोप२ पटक</p>')
        self.assertEqual(used, ['diabetes', 'vaccine'])
        self.assertIn('>मधुमेह</a>।', html)
        self.assertIn('>खोप</a>२', html)

    def test_never_inside_another_nepali_word(self):
        html, used = self.mark('<p>खोपडीमा चोट लाग्यो।</p>')  # skull, not vaccine
        self.assertEqual(used, [])

    def test_english_whole_words_any_case_and_caps_exact(self):
        html, used = self.mark('<p>diabetes rates rise; prediabetes too. People who smoke. The WHO says so.</p>')
        self.assertEqual(used, ['diabetes', 'who'])
        self.assertIn('>diabetes</a> rates', html)
        self.assertIn('prediabetes too', html)  # not inside a longer word
        self.assertNotIn('>who</a>', html)
        self.assertIn('>WHO</a>', html)

    def test_skips_links_headings_code_and_citations(self):
        html, used = self.mark('<h2>Diabetes</h2><p><a href="/x">diabetes</a> <code>diabetes</code> '
                               '<sup><a href="#ref-1">1</a></sup></p><figure><figcaption>Diabetes</figcaption></figure>')
        self.assertEqual(used, [])
        html, used = self.mark('<h2>Diabetes</h2><p>Living with diabetes.</p>')
        self.assertIn('<h2>Diabetes</h2>', html)
        self.assertIn('with <a', html)

    def test_unpublished_ignored_and_limit(self):
        html, used = self.mark('<p>Hidden diabetes vaccine WHO</p>', max_marks=2)
        self.assertEqual(used, ['diabetes', 'vaccine'])

    def test_cache_refreshes_when_a_term_changes(self):
        self.assertEqual(self.mark('<p>Malaria</p>')[1], [])
        from .models import GlossaryTerm

        GlossaryTerm.objects.create(term_en='Malaria', definition_en='A mosquito-borne disease.', is_published=True)
        self.assertEqual(self.mark('<p>Malaria</p>')[1], ['malaria'])

    def test_article_page_marks_terms_and_ships_definitions(self):
        article = Article.objects.create(title='Sugar story', status=Article.Status.PUBLISHED,
                                         html_content='<p>मधुमेहका बिरामी बढे। The WHO warned.</p>')
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, 'class="glossary-term" data-glossary="diabetes"')
        self.assertEqual(set(response.context['glossary_definitions']), {'diabetes', 'who'})
        self.assertContains(response, 'id="glossary-data"')
        self.assertContains(response, 'id="glossary-labels"')
        # Stored text is untouched: marking happens at render time.
        article.refresh_from_db()
        self.assertNotIn('glossary-term', article.html_content)

    def test_article_switch_turns_marking_off(self):
        article = Article.objects.create(title='Explainer', status=Article.Status.PUBLISHED,
                                         html_content='<p>मधुमेहका बिरामी बढे।</p>')
        self.assertTrue(article.glossary_marking)  # on by default
        article.glossary_marking = False
        article.save()
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertNotContains(response, 'glossary-term')
        self.assertNotContains(response, 'id="glossary-data"')
        self.assertContains(response, 'मधुमेहका बिरामी')

    def test_locked_article_skips_marking(self):
        from unittest.mock import patch

        article = Article.objects.create(title='Locked', status=Article.Status.PUBLISHED,
                                         access_type=Article.AccessType.SUBSCRIPTION,
                                         html_content='<p>मधुमेहका बिरामी बढे।</p>')
        with patch('billing.access.FREE_SAMPLE_LIMIT_PER_MONTH', 0):
            response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertFalse(response.context['show_full_text'])
        self.assertNotContains(response, 'id="glossary-data"')

    def test_preview_follows_the_checkbox(self):
        editor = User.objects.create_user(email='pv@example.com', password='pw', first_name='P', last_name='V',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        data = {'title': 'Preview story', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
                'access_type': Article.AccessType.OPEN_ACCESS, 'html_content': '<p>मधुमेह बढ्यो।</p>',
                'featured_image_fit': 'cover'}
        url = reverse('articles:manage_article_preview')
        marked = self.client.post(url, {**data, 'glossary_marking': 'on'})
        self.assertContains(marked, 'class="glossary-term"')
        unmarked = self.client.post(url, data)  # unticked checkbox: not sent
        self.assertEqual(unmarked.status_code, 200)
        self.assertNotContains(unmarked, 'class="glossary-term"')

    def test_no_terms_no_script(self):
        article = Article.objects.create(title='Plain', status=Article.Status.PUBLISHED, html_content='<p>Nothing here.</p>')
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertNotContains(response, 'id="glossary-data"')


class LibraryAcrossTheSiteTests(TestCase):
    """The library on article pages, topic pages, site search and the menu."""

    def setUp(self):
        self.malaria = Keyword.objects.create(name='Malaria', slug='malaria')
        self.article = Article.objects.create(title='Malaria returns to the Terai', status=Article.Status.PUBLISHED,
                                              html_content='<p>Malaria cases are rising again in the Terai.</p>')
        self.article.keyword_tags.add(self.malaria)
        self.linked = make('National Malaria Treatment Protocol', resource_type=Resource.ResourceType.GUIDELINE,
                           source='EDCD')
        self.linked.related_articles.add(self.article)
        self.linked.keyword_tags.add(self.malaria)
        self.unlinked = make('Malaria Programme Review 2023')
        self.unlinked.keyword_tags.add(self.malaria)
        self.hidden = make('Hidden malaria draft', is_published=False)
        self.hidden.related_articles.add(self.article)
        self.hidden.keyword_tags.add(self.malaria)

    def test_article_page_shows_only_linked_published_documents(self):
        response = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertEqual(response.context['library_resources'], [self.linked])
        self.assertContains(response, 'National Malaria Treatment Protocol')
        self.assertNotContains(response, 'Hidden malaria draft')

    def test_topic_page_shows_tagged_documents(self):
        response = self.client.get(reverse('articles:topic_detail', args=['malaria']))
        self.assertCountEqual(response.context['library_resources'], [self.linked, self.unlinked])
        self.assertEqual(response.context['library_total'], 2)

    def test_site_search_includes_library(self):
        response = self.client.get(reverse('articles:search'), {'q': 'malaria protocol'})
        self.assertEqual(response.context['library_results'], [self.linked])
        self.assertContains(response, 'National Malaria Treatment Protocol')

    def test_library_search_matches_every_word_in_any_order(self):
        from .queries import matching, published

        self.assertEqual(list(matching(published(), 'protocol malaria')), [self.linked])
        self.assertEqual(list(matching(published(), 'edcd treatment')), [self.linked])
        self.assertFalse(matching(published(), 'malaria cholera').exists())

    def test_menu_entry_exists_hidden(self):
        from sections.models import Section

        entry = Section.objects.get(link_url_name='library:resource_list')
        self.assertFalse(entry.is_active)
        self.assertEqual(entry.nav_url, '/library/')

    def test_section_form_offers_library_and_rejects_unknown_route(self):
        from sections.forms import SectionForm

        form = SectionForm()
        self.assertIn('library:resource_list', dict(form.fields['link_url_name'].choices))
        form = SectionForm(data={'name_en': 'X', 'name_ne': 'X', 'slug': 'x', 'order': 1, 'is_active': True,
                                 'link_url_name': 'nope:missing'})
        self.assertFalse(form.is_valid())
        self.assertIn('link_url_name', form.errors)
