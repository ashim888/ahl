"""The launch checklist (z_CHECKS.md) items built in code: image optimization
on upload, privacy notices on data-collecting forms, the health disclaimer,
form loading states, the FAQ page, meta descriptions, favicons and the
default share image, and the sticky subscribe bar on phones."""
import datetime
import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from ajna_health_lens.ckeditor_views import InlineImageStorage
from ajna_health_lens.images import optimize_bytes
from articles.models import Article
from billing.test_lifecycle import make_plan, make_user, subscribe
from editorial_board.models import EditorialBoardMember
from pages.models import SitePage
from users.models import User


def jpeg_bytes(size=(3000, 2000), exif=True, color=(200, 80, 60)) -> bytes:
    image = Image.new('RGB', size, color)
    out = io.BytesIO()
    kwargs = {}
    if exif:
        data = Image.Exif()
        data[0x0110] = 'Secret phone model'  # Model
        data[0x0112] = 6  # Orientation: rotate 90° when shown
        kwargs['exif'] = data.tobytes()
    image.save(out, 'JPEG', quality=100, **kwargs)
    return out.getvalue()


class OptimizeBytesTests(TestCase):
    def test_large_photo_is_resized_turned_upright_and_stripped(self):
        result = optimize_bytes(jpeg_bytes())
        image = Image.open(io.BytesIO(result))
        self.assertEqual(max(image.size), 2400)
        self.assertGreater(image.height, image.width)  # orientation applied
        self.assertFalse(image.getexif())

    def test_keep_size_never_resizes(self):
        result = optimize_bytes(jpeg_bytes(), keep_size=True)
        self.assertEqual(Image.open(io.BytesIO(result)).size, (2000, 3000))

    def test_small_clean_image_left_alone_unless_smaller(self):
        image = Image.new('RGB', (40, 40), (255, 255, 255))
        out = io.BytesIO()
        image.save(out, 'JPEG', quality=60)
        result = optimize_bytes(out.getvalue())
        self.assertTrue(result is None or len(result) < len(out.getvalue()))

    def test_gif_and_garbage_untouched(self):
        out = io.BytesIO()
        Image.new('P', (10, 10)).save(out, 'GIF')
        self.assertIsNone(optimize_bytes(out.getvalue()))
        self.assertIsNone(optimize_bytes(b'not an image'))

    def test_broken_image_never_breaks_the_upload(self):
        out = io.BytesIO()
        Image.new('RGB', (20, 20)).save(out, 'PNG')
        self.assertIsNone(optimize_bytes(out.getvalue()[:-20]))  # truncated: Pillow raises SyntaxError


class UploadOptimizationTests(TestCase):
    def test_model_image_upload_is_optimized(self):
        original = jpeg_bytes()
        member = EditorialBoardMember.objects.create(
            name='Dr. Rai', role_title='Editor', photo=SimpleUploadedFile('rai.jpg', original, content_type='image/jpeg'),
        )
        member.refresh_from_db()
        with member.photo.open('rb') as handle:
            stored = handle.read()
        self.assertLess(len(stored), len(original))
        self.assertEqual(max(Image.open(io.BytesIO(stored)).size), 2400)
        self.assertTrue(member.photo.name.endswith('.jpg'))

    def test_resaving_without_new_upload_does_not_reprocess(self):
        member = EditorialBoardMember.objects.create(
            name='Dr. Rai', role_title='Editor', photo=SimpleUploadedFile('rai.jpg', jpeg_bytes(), content_type='image/jpeg'),
        )
        name = member.photo.name
        member.name = 'Dr. B. Rai'
        member.save()
        self.assertEqual(member.photo.name, name)

    @override_settings(IMAGE_OPTIMIZE_UPLOADS=False)
    def test_can_be_switched_off(self):
        original = jpeg_bytes(size=(500, 400))
        member = EditorialBoardMember.objects.create(
            name='Dr. Rai', role_title='Editor', photo=SimpleUploadedFile('rai.jpg', original, content_type='image/jpeg'),
        )
        with member.photo.open('rb') as handle:
            self.assertEqual(handle.read(), original)

    def test_inline_editor_images_are_optimized(self):
        storage = InlineImageStorage()
        name = storage.save('photo.jpg', SimpleUploadedFile('photo.jpg', jpeg_bytes(), content_type='image/jpeg'))
        try:
            with storage.open(name) as handle:
                self.assertEqual(max(Image.open(handle).size), 2400)
        finally:
            storage.delete(name)


class CompressImagesCommandTests(TestCase):
    def setUp(self):
        self.media = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)

    def test_compresses_existing_inline_images_in_place(self):
        path = self.media / 'articles' / 'inline' / '2026' / '01' / 'old.jpg'
        path.parent.mkdir(parents=True)
        path.write_bytes(jpeg_bytes())
        before = path.stat().st_size
        out = io.StringIO()
        with override_settings(MEDIA_ROOT=str(self.media)):
            call_command('compress_images', '--dry-run', stdout=out)
            self.assertEqual(path.stat().st_size, before)
            self.assertIn('Would optimize 1 image', out.getvalue())
            call_command('compress_images', stdout=io.StringIO())
        self.assertLess(path.stat().st_size, before)


class FormNoticeTests(TestCase):
    def setUp(self):
        SitePage.objects.filter(slug='privacy').update(is_published=True)
        SitePage.objects.filter(slug='privacy').first().save()  # clears the published-pages cache
        self.article = Article.objects.create(
            title='Clean water', slug='clean-water', status=Article.Status.PUBLISHED, html_content='<p>Text</p>',
            publication_date=timezone.localdate(),
        )

    def test_newsletter_forms_explain_and_link_privacy_policy(self):
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, 'We use your email only to send the newsletter', count=2)
        self.assertContains(response, reverse('pages:privacy'))

    def test_comment_pitch_and_report_forms_have_notices(self):
        self.assertContains(self.client.get(self.article.get_absolute_url()), 'your email isn’t')
        self.assertContains(self.client.get(reverse('pitches:pitch_create')), 'only to review your pitch')
        self.assertContains(self.client.get(reverse('report_content'), {'article': self.article.pk}),
                            'used only to reply about this report')

    def test_article_shows_health_disclaimer(self):
        response = self.client.get(self.article.get_absolute_url())
        self.assertContains(response, 'Not medical advice.')
        self.assertContains(response, 'call 102')

    def test_loading_script_and_loading_text(self):
        self.assertContains(self.client.get(reverse('articles:home')), 'js/form_loading.js')
        self.assertContains(self.client.get(reverse('users:register')), 'data-loading-text=')
        self.assertContains(self.client.get(reverse('pitches:pitch_create')), 'data-loading-text=')


class FaqPageTests(TestCase):
    def test_faq_is_a_draft_until_published(self):
        self.assertEqual(self.client.get(reverse('pages:faq')).status_code, 404)
        self.assertNotContains(self.client.get(reverse('articles:home')), reverse('pages:faq'))

    def test_published_faq_page_footer_sitemap_and_structured_data(self):
        page = SitePage.objects.get(slug='faq')
        page.is_published = True
        page.save()
        response = self.client.get(reverse('pages:faq'))
        self.assertContains(response, '"@type": "FAQPage"')
        self.assertContains(response, 'Does my subscription renew automatically?')
        self.assertContains(response, '<meta name="description" content="Answers about subscriptions')
        self.assertContains(self.client.get(reverse('articles:home')), reverse('pages:faq'))
        self.assertContains(self.client.get('/sitemap.xml'), '/faq/')

    def test_faq_is_not_listed_among_legal_pages(self):
        for slug in ('faq', 'terms'):
            page = SitePage.objects.get(slug=slug)
            page.is_published = True
            page.save()
        response = self.client.get(reverse('articles:home'))
        self.assertNotIn('faq', [p.slug for p in response.context['legal_pages']])


class HeadTests(TestCase):
    def test_favicons_manifest_and_share_image(self):
        response = self.client.get(reverse('articles:home'))
        for snippet in ('favicon.ico', 'apple-touch-icon.png', 'site.webmanifest', 'og-default.png'):
            self.assertContains(response, snippet)

    def test_favicon_ico_redirects_to_static(self):
        response = self.client.get('/favicon.ico')
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response['Location'].endswith('favicon.ico'))

    def test_page_specific_descriptions(self):
        for url, text in ((reverse('billing:plan_browse'), 'No automatic renewal'),
                          (reverse('pitches:pitch_create'), 'Pitch it to the editors'),
                          (reverse('users:register'), 'Create a free')):
            self.assertContains(self.client.get(url), text)


class SubscribeBarTests(TestCase):
    MARK = 'id="mobile-subscribe-bar"'

    def test_shown_to_anonymous_readers(self):
        self.assertContains(self.client.get(reverse('articles:home')), self.MARK)

    def test_not_on_plans_or_checkout_style_pages(self):
        self.assertNotContains(self.client.get(reverse('billing:plan_browse')), self.MARK)
        self.assertNotContains(self.client.get(reverse('pitches:pitch_thanks')), self.MARK)

    def test_hidden_for_subscribers_and_staff(self):
        reader = make_user('reader@example.com')
        today = timezone.localdate()
        subscribe(reader, make_plan(), today, today + datetime.timedelta(days=30))
        self.client.force_login(reader)
        self.assertNotContains(self.client.get(reverse('articles:home')), self.MARK)
        editor = make_user('ed@example.com', role=User.Role.EDITOR)
        self.client.force_login(editor)
        self.assertNotContains(self.client.get(reverse('articles:home')), self.MARK)

    def test_shown_to_signed_in_non_subscribers(self):
        self.client.force_login(make_user('free@example.com'))
        self.assertContains(self.client.get(reverse('articles:home')), self.MARK)
