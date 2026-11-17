"""Article audio: an audio summary or a podcast episode, private and streamable."""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from ajna_health_lens.validators import validate_document_content

from .forms import ArticleForm
from .models import Article

MP3 = b'ID3\x04\x00\x00\x00\x00\x00\x00' + bytes(range(256)) * 4  # 1034 bytes


class AudioTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        override = override_settings(PRIVATE_MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)

    def story(self, **extra):
        article = Article.objects.create(title='Episode 1', status=Article.Status.PUBLISHED,
                                         article_type=Article.ArticleType.PODCAST, **extra)
        article.audio_file.save('episode.mp3', ContentFile(MP3))
        return article

    def test_upload_must_really_be_audio(self):
        validate_document_content(SimpleUploadedFile('a.mp3', MP3))
        validate_document_content(SimpleUploadedFile('a.m4a', b'\x00\x00\x00\x20ftypM4A '))
        with self.assertRaises(ValidationError):
            validate_document_content(SimpleUploadedFile('a.mp3', b'<html>not audio</html>'))

    def test_podcast_needs_audio(self):
        data = {'title': 'Ep', 'article_type': 'podcast', 'access_type': 'open_access', 'featured_image_fit': 'cover'}
        form = ArticleForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('audio_file', form.errors)
        form = ArticleForm(data=data, files={'audio_file': SimpleUploadedFile('ep.mp3', MP3)})
        self.assertTrue(form.is_valid(), form.errors)

    def test_player_and_byte_ranges(self):
        article = self.story()
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, '<audio controls')
        url = article.audio_file.url
        part = self.client.get(url, HTTP_RANGE='bytes=10-19')
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part['Content-Range'], f'bytes 10-19/{len(MP3)}')
        self.assertEqual(b''.join(part.streaming_content), MP3[10:20])
        tail = self.client.get(url, HTTP_RANGE='bytes=-4')
        self.assertEqual(b''.join(tail.streaming_content), MP3[-4:])
        self.assertEqual(self.client.get(url, HTTP_RANGE=f'bytes={len(MP3)}-').status_code, 416)
        whole = self.client.get(url)
        self.assertEqual(whole.status_code, 200)
        self.assertEqual(whole['Accept-Ranges'], 'bytes')

    def test_autosave_without_the_file_keeps_the_audio(self):
        # The editor's autosave leaves file inputs out (article_form.html), so a
        # chosen file isn't re-uploaded every 20 seconds; the saved one must stay.
        from users.models import User

        editor = User.objects.create_user(email='au@example.com', password='pw', first_name='A', last_name='U',
                                          role=User.Role.EDITOR)
        self.client.force_login(editor)
        draft = Article.objects.create(title='Draft episode', article_type=Article.ArticleType.PODCAST)
        draft.audio_file.save('episode.mp3', ContentFile(MP3))
        name = draft.audio_file.name
        response = self.client.post(reverse('articles:manage_article_autosave'), {
            'title': 'Draft episode, retitled', 'article_type': 'podcast', 'article_pk': draft.pk,
            'edit_token': f'{draft.updated_at.timestamp():.6f}'})
        self.assertTrue(response.json()['ok'], response.content)
        draft.refresh_from_db()
        self.assertEqual(draft.title, 'Draft episode, retitled')
        self.assertEqual(draft.audio_file.name, name)
        self.assertEqual(len(list(Path(self.media).rglob('*.mp3'))), 1)

    def test_locked_story_hides_audio(self):
        article = self.story(access_type=Article.AccessType.SUBSCRIPTION)
        with patch('billing.access.FREE_SAMPLE_LIMIT_PER_MONTH', 0):
            response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
            self.assertNotContains(response, '<audio')
            self.assertContains(response, 'SUBSCRIBE TO LISTEN')
            self.assertEqual(self.client.get(article.audio_file.url).status_code, 302)  # to the paywall
