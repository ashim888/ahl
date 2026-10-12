"""Search & social is automatic: the search headline and description come
from the headline and summary (Article.meta_title / meta_description), and
the share picture is a 1200×630 card made from the featured image
(articles/share_card.py). The editor's fields are overrides only."""
import io

from django.core.files.storage import default_storage
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from users.models import User

from .models import Article
from .share_card import HEIGHT, WIDTH, card_name, render, share_card_url
from .test_image_framing import image_file, make


def png(size, colour=(200, 80, 60), mode='RGB'):
    out = io.BytesIO()
    Image.new(mode, size, colour).save(out, 'PNG')
    return out.getvalue()


class MetaTextTests(TestCase):
    def test_headline_and_summary_are_used_automatically(self):
        article = Article(title='Dengue cases rise', abstract='Cases rose 35% this week.')
        self.assertEqual(article.meta_title, 'Dengue cases rise')
        self.assertEqual(article.meta_description, 'Cases rose 35% this week.')

    def test_overrides_win(self):
        article = Article(title='Dengue cases rise', abstract='Long summary.', seo_title='Dengue in Nepal',
                          seo_description='Short.')
        self.assertEqual((article.meta_title, article.meta_description), ('Dengue in Nepal', 'Short.'))

    def test_blank_override_is_automatic(self):
        article = Article(title='Dengue cases rise', abstract='Summary.', seo_title='   ', seo_description=' ')
        self.assertEqual((article.meta_title, article.meta_description), ('Dengue cases rise', 'Summary.'))

    def test_long_summary_is_cut_at_a_word(self):
        article = Article(title='T', abstract='word ' * 60)
        description = article.meta_description
        self.assertLessEqual(len(description), Article.META_DESCRIPTION_LENGTH)
        self.assertTrue(description.endswith('word…'))

    def test_paid_story_without_summary_never_leaks_body_text(self):
        article = Article(title='T', html_content='<p>Secret paywalled text.</p>',
                          access_type=Article.AccessType.SUBSCRIPTION)
        self.assertEqual(article.meta_description, '')


class RenderTests(TestCase):
    def size(self, data):
        return Image.open(io.BytesIO(data)).size

    def test_every_card_is_1200_by_630(self):
        for size in ((1600, 900), (800, 1200), (1000, 1000), (3000, 600), (300, 200)):
            for whole in (True, False):
                self.assertEqual(self.size(render(png(size), whole=whole)), (WIDTH, HEIGHT))

    def test_crop_keeps_the_focal_point(self):
        # A tall picture: top half red, bottom half blue. Focus at the bottom → blue card.
        image = Image.new('RGB', (600, 1200), (255, 0, 0))
        image.paste((0, 0, 255), (0, 600, 600, 1200))
        out = io.BytesIO()
        image.save(out, 'PNG')
        card = Image.open(io.BytesIO(render(out.getvalue(), whole=False, focus_y=95)))
        red, green, blue = card.getpixel((WIDTH // 2, HEIGHT // 2))
        self.assertGreater(blue, 200)
        self.assertLess(red, 50)

    def test_whole_picture_sits_on_a_backdrop(self):
        card = Image.open(io.BytesIO(render(png((800, 1200), (255, 255, 255)), whole=True)))
        self.assertEqual(card.getpixel((WIDTH // 2, HEIGHT // 2)), (255, 255, 255))
        self.assertLess(sum(card.getpixel((10, HEIGHT // 2))), 600)  # darkened fill at the sides

    def test_transparent_png_goes_on_white(self):
        card = Image.open(io.BytesIO(render(png((1200, 630), (0, 0, 0, 0), mode='RGBA'), whole=False)))
        self.assertEqual(card.getpixel((5, 5)), (255, 255, 255))


class ArticlePageTests(TestCase):
    def test_article_page_shares_the_automatic_card(self):
        article = make((800, 1200))
        response = self.client.get(article.get_absolute_url())
        name = card_name(article)
        self.assertTrue(default_storage.exists(name))
        self.assertContains(response, f'<meta property="og:image" content="http://testserver{default_storage.url(name)}">')
        self.assertContains(response, '<title>Brain regions explained — ')

    def test_card_is_made_once_and_remade_when_the_framing_changes(self):
        article = make((1600, 900))
        first = share_card_url(article)
        self.assertEqual(share_card_url(article), first)
        article.featured_image_focus_x = 10
        article.save()
        self.assertNotEqual(share_card_url(article), first)

    def test_uploaded_share_image_wins(self):
        article = make((1600, 900))
        article.social_image = image_file((1200, 630), name='mine.png')
        article.save()
        response = self.client.get(article.get_absolute_url())
        self.assertContains(response, f'content="http://testserver{article.social_image.url}"')
        self.assertFalse(default_storage.exists(card_name(article)))

    def test_missing_featured_file_falls_back_quietly(self):
        article = make((1600, 900))
        default_storage.delete(article.featured_image.name)
        self.assertEqual(share_card_url(article), '')
        self.assertEqual(self.client.get(article.get_absolute_url()).status_code, 200)

    def test_no_image_no_card(self):
        article = Article.objects.create(title='No picture', status=Article.Status.PUBLISHED, html_content='<p>x</p>')
        self.assertEqual(share_card_url(article), '')


class EditorTests(TestCase):
    def test_editor_shows_automatic_previews_with_overrides_tucked_away(self):
        editor = User.objects.create_user(email='ed@example.com', password='pw', first_name='E', last_name='D',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        page = self.client.get(reverse('articles:manage_article_create'))
        self.assertContains(page, 'id="preview-share"')
        self.assertContains(page, 'Use different words or picture')
        self.assertNotContains(page, 'Search &amp; social <span class="font-normal text-gray-400 text-xs">(optional)')

    def test_ticking_the_box_removes_an_uploaded_share_image(self):
        editor = User.objects.create_user(email='ed2@example.com', password='pw', first_name='E', last_name='D',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        article = Article.objects.create(title='Shared', social_image=image_file((1200, 630), name='mine.png'))
        page = self.client.get(reverse('articles:manage_article_update', args=[article.slug]))
        self.assertContains(page, 'name="social_image-clear"')
        self.assertNotContains(page, 'Currently:')
        self.client.post(reverse('articles:manage_article_update', args=[article.slug]), {
            'title': 'Shared', 'slug': article.slug, 'article_type': Article.ArticleType.NEWS_COMMENTARY,
            'access_type': Article.AccessType.OPEN_ACCESS, 'action': 'draft', 'social_image-clear': 'on',
        })
        article.refresh_from_db()
        self.assertFalse(article.social_image)
