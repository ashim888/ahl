"""Accessibility guarantees (WCAG 2.1 AA) — checked in the browser with
axe-core across the main pages; these tests keep the fixes from regressing."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from users.models import User

from .forms import images_missing_alt
from .models import Article
from .tests import grant_publish

def png_bytes():
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', (40, 30), 'white').save(buffer, format='PNG')
    return buffer.getvalue()


class PageStructureTests(TestCase):
    def test_skip_link_main_landmark_and_labelled_regions(self):
        page = self.client.get(reverse('articles:home'))
        self.assertContains(page, 'href="#main"')
        self.assertContains(page, '<main id="main"')
        self.assertContains(page, 'aria-label="Main"')
        self.assertContains(page, 'aria-label="Latest issue"')

    def test_article_controls_have_text_for_screen_readers(self):
        article = Article.objects.create(title='A', slug='a11y-story', status=Article.Status.PUBLISHED, html_content='<p>x</p>')
        page = self.client.get(article.get_absolute_url())
        self.assertContains(page, '<span class="sr-only">Share on X</span>')
        self.assertContains(page, '<span class="sr-only">Decrease text size</span>')
        self.assertContains(page, 'aria-label="Share"')

    def test_homepage_headings_never_skip_a_level(self):
        self.assertNotContains(self.client.get(reverse('articles:home')), '<h4')


class ImageDescriptionTests(TestCase):
    def test_counting_images_without_alt(self):
        self.assertEqual(images_missing_alt('<p><img src="a.png"><img src="b.png" alt=""><img alt="A clinic" src="c.png"></p>'), 2)
        self.assertEqual(images_missing_alt("<img src='a.png' alt='Nurse'>"), 0)
        self.assertEqual(images_missing_alt(''), 0)

    def _publish(self, **extra):
        editor = User.objects.create_user(email='a11y-editor@example.com', password='pw', first_name='E', last_name='D',
                                          role=User.Role.EDITOR)
        grant_publish(editor)
        self.client.force_login(editor)
        data = {
            'title': 'Clinic photos', 'slug': 'clinic-photos', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'abstract': 'x', 'action': 'publish',
            'html_content': '<p>Text</p><figure class="image"><img src="/media/x.png"></figure>',
        }
        data.update(extra)
        return self.client.post(reverse('articles:manage_article_create'), data)

    def test_publishing_needs_image_descriptions(self):
        response = self._publish()
        self.assertContains(response, '1 image in the text has no description')
        self.assertFalse(Article.objects.filter(status=Article.Status.PUBLISHED).exists())

    def test_described_images_publish(self):
        self._publish(html_content='<p>Text</p><img src="/media/x.png" alt="Nurses at the Jumla clinic">')
        self.assertTrue(Article.objects.filter(slug='clinic-photos', status=Article.Status.PUBLISHED).exists())

    def test_featured_image_description_defaults_to_the_slug(self):
        self._publish(html_content='<p>Text</p>', featured_image=SimpleUploadedFile('f.png', png_bytes(), 'image/png'))
        article = Article.objects.get(slug='clinic-photos')
        self.assertEqual(article.status, Article.Status.PUBLISHED)
        self.assertEqual(article.featured_image_alt, 'Clinic photos')

    def test_an_editors_own_description_is_kept(self):
        self._publish(html_content='<p>Text</p>', featured_image=SimpleUploadedFile('f.png', png_bytes(), 'image/png'),
                      featured_image_alt='Nurses outside the Jumla clinic')
        self.assertEqual(Article.objects.get(slug='clinic-photos').featured_image_alt, 'Nurses outside the Jumla clinic')

    def test_alt_from_slug(self):
        from .slugs import alt_from_slug

        self.assertEqual(alt_from_slug('dengue-cases-rise-kathmandu'), 'Dengue cases rise kathmandu')
        self.assertEqual(alt_from_slug('dengue-cases-rise-2'), 'Dengue cases rise')
        self.assertEqual(alt_from_slug('covid-19'), 'Covid')  # a short trailing number reads as a clash suffix
        self.assertEqual(alt_from_slug(''), '')

    def test_saving_without_the_form_fills_it_too(self):
        article = Article.objects.create(title='Clinic photos', featured_image=SimpleUploadedFile('g.png', png_bytes(), 'image/png'))
        self.assertEqual(article.featured_image_alt, 'Clinic photos')
