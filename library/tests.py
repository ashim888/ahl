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
