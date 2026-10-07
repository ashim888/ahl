"""Featured image framing: square/tall images (diagrams) shown whole, wide
photos cropped around an editor-chosen focal point — on the article banner,
cards and lists (Article.featured_image_fit / _focus_x / _focus_y)."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from users.models import User

from .models import Article


def image_file(size, name='pic.png', exif_orientation=None):
    out = io.BytesIO()
    kwargs = {}
    fmt = 'PNG'
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs['exif'] = exif.tobytes()
        fmt, name = 'JPEG', name.replace('.png', '.jpg')
    Image.new('RGB', size, (200, 80, 60)).save(out, fmt, **kwargs)
    return SimpleUploadedFile(name, out.getvalue(), content_type=f'image/{fmt.lower()}')


def make(size, **extra):
    return Article.objects.create(title='Brain regions explained', status=Article.Status.PUBLISHED,
                                  html_content='<p>x</p>', featured_image=image_file(size), **extra)


class FitTests(TestCase):
    def test_dimensions_are_recorded(self):
        article = make((1312, 1199))
        self.assertEqual((article.featured_image_width, article.featured_image_height), (1312, 1199))

    def test_auto_shows_square_and_tall_images_whole_and_crops_wide_ones(self):
        self.assertTrue(make((1312, 1199)).featured_image_shows_whole)
        self.assertTrue(make((800, 1200)).featured_image_shows_whole)
        self.assertFalse(make((1600, 900)).featured_image_shows_whole)

    def test_editor_choice_wins(self):
        self.assertFalse(make((1000, 1000), featured_image_fit=Article.ImageFit.COVER).featured_image_shows_whole)
        self.assertTrue(make((1600, 900), featured_image_fit=Article.ImageFit.CONTAIN).featured_image_shows_whole)

    def test_card_style(self):
        self.assertIn('object-fit: contain', make((1000, 1000)).card_image_style)
        wide = make((1600, 900), featured_image_focus_x=30, featured_image_focus_y=10)
        self.assertEqual(wide.card_image_style, 'object-position: 30% 10%;')
        self.assertEqual(Article.objects.create(title='No image').card_image_style, '')

    def test_missing_image_file_never_breaks_the_page(self):
        # A row pointing at a file that isn't on disk (deleted, not yet synced…).
        article = Article.objects.create(title='Lost file', status=Article.Status.PUBLISHED, html_content='<p>x</p>',
                                         featured_image='articles/images/not-there.jpg')
        self.assertIsNone(article.featured_image_width)
        self.assertFalse(article.featured_image_shows_whole)
        self.assertEqual(self.client.get(article.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(reverse('articles:article_list')).status_code, 200)

    def test_rotated_phone_photo_gets_the_upright_dimensions(self):
        # Stored 1600×900 with "rotate 90°" — shown (and optimized) upright as 900×1600.
        article = Article.objects.create(title='Phone photo', featured_image=image_file((1600, 900), exif_orientation=6))
        self.assertEqual((article.featured_image_width, article.featured_image_height), (900, 1600))
        self.assertTrue(article.featured_image_shows_whole)


class RenderingTests(TestCase):
    def test_article_banner_shows_a_diagram_whole_on_a_blurred_backdrop(self):
        article = make((1312, 1199))
        response = self.client.get(article.get_absolute_url())
        self.assertContains(response, 'blur-2xl')
        self.assertContains(response, 'width="1312" height="1199"')

    def test_wide_photo_banner_uses_the_focal_point(self):
        article = make((1600, 900), featured_image_focus_x=20, featured_image_focus_y=75)
        response = self.client.get(article.get_absolute_url())
        self.assertContains(response, 'object-position: 20% 75%;')
        self.assertNotContains(response, 'blur-2xl')

    def test_cards_and_lists_carry_the_style(self):
        make((1000, 1000))
        self.assertContains(self.client.get(reverse('articles:article_list')), 'object-fit: contain')

    def test_editor_saves_fit_and_focal_point(self):
        editor = User.objects.create_user(email='ed@example.com', password='pw', first_name='E', last_name='D',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        page = self.client.get(reverse('articles:manage_article_create'))
        self.assertContains(page, 'id="focus-picker"')
        self.client.post(reverse('articles:manage_article_create'), {
            'title': 'Framed', 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'action': 'draft', 'featured_image_fit': 'cover',
            'featured_image_focus_x': 35, 'featured_image_focus_y': 15, 'featured_image': image_file((1600, 900)),
        })
        article = Article.objects.get(title='Framed')
        self.assertEqual((article.featured_image_fit, article.featured_image_focus_x, article.featured_image_focus_y),
                         ('cover', 35, 15))
