from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from articles.models import Article, ArticleAuthor
from users.models import User

from .models import StoryPitch

# These tests create several users per test via create_user() (real PBKDF2
# hashing each time) — same slowness/flake-risk pattern documented in
# ARCHITECTURE.md §9.4 and users/tests.py:FAST_PASSWORD_HASHERS.
FAST_PASSWORD_HASHERS = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def make_verified_author(email='author@example.com'):
    return User.objects.create_user(
        email=email, password='pw', first_name='A', last_name='U', role=User.Role.VERIFIED_AUTHOR,
    )


def make_editor(email='editor@example.com'):
    return User.objects.create_user(
        email=email, password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
    )


@FAST_PASSWORD_HASHERS
class PitchSubmissionAccessTests(TestCase):
    def test_verified_author_can_view_submit_form(self):
        self.client.force_login(make_verified_author())
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertEqual(response.status_code, 200)

    def test_unverified_user_cannot_submit(self):
        reader = User.objects.create_user(email='reader@example.com', password='pw', first_name='R', last_name='D')
        self.client.force_login(reader)
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertEqual(response.status_code, 403)

    def test_editorial_staff_cannot_submit(self):
        # Deliberate: editors write articles directly, they don't pitch — see PITCH_SUBMIT_ROLES.
        self.client.force_login(make_editor())
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)


@FAST_PASSWORD_HASHERS
class PitchSubmissionTests(TestCase):
    def setUp(self):
        self.author = make_verified_author()
        self.client.force_login(self.author)

    def test_submitting_creates_pitch_owned_by_submitter(self):
        response = self.client.post(reverse('pitches:pitch_create'), {
            'title': 'A Story About Rural Clinics', 'summary': 'Why this matters now.', 'body': '',
        })
        self.assertEqual(response.status_code, 302)
        pitch = StoryPitch.objects.get(title='A Story About Rural Clinics')
        self.assertEqual(pitch.submitter, self.author)
        self.assertEqual(pitch.status, StoryPitch.Status.SUBMITTED)

    def test_honeypot_blocks_submission(self):
        self.client.post(reverse('pitches:pitch_create'), {
            'title': 'Spam Pitch', 'summary': 'x', 'website': 'http://spam.example',
        })
        self.assertFalse(StoryPitch.objects.filter(title='Spam Pitch').exists())

    def test_excessive_submissions_are_rate_limited(self):
        # Limit is 10/h by user (pitches/views.py PITCH_SUBMIT_ROLES / ratelimit).
        for i in range(10):
            self.client.post(reverse('pitches:pitch_create'), {'title': f'Pitch {i}', 'summary': 'x'})
        response = self.client.post(reverse('pitches:pitch_create'), {'title': 'Pitch overflow', 'summary': 'x'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(StoryPitch.objects.filter(title='Pitch overflow').exists())


@FAST_PASSWORD_HASHERS
class MyPitchesListTests(TestCase):
    def test_only_shows_own_pitches(self):
        mine = make_verified_author('mine@example.com')
        theirs = make_verified_author('theirs@example.com')
        StoryPitch.objects.create(title='Mine', summary='s', submitter=mine)
        StoryPitch.objects.create(title='Theirs', summary='s', submitter=theirs)

        self.client.force_login(mine)
        response = self.client.get(reverse('pitches:my_pitches'))
        titles = [p.title for p in response.context['pitches']]
        self.assertIn('Mine', titles)
        self.assertNotIn('Theirs', titles)


@FAST_PASSWORD_HASHERS
class PitchQueueAccessTests(TestCase):
    def test_editor_can_access_queue(self):
        self.client.force_login(make_editor())
        response = self.client.get(reverse('pitches:manage_pitch_queue'))
        self.assertEqual(response.status_code, 200)

    def test_verified_author_cannot_access_queue(self):
        self.client.force_login(make_verified_author())
        response = self.client.get(reverse('pitches:manage_pitch_queue'))
        self.assertEqual(response.status_code, 403)

    def test_queue_defaults_to_open_pitches_only(self):
        author = make_verified_author()
        open_pitch = StoryPitch.objects.create(title='Open', summary='s', submitter=author, status=StoryPitch.Status.SUBMITTED)
        StoryPitch.objects.create(title='Closed', summary='s', submitter=author, status=StoryPitch.Status.REJECTED)

        self.client.force_login(make_editor())
        response = self.client.get(reverse('pitches:manage_pitch_queue'))
        pitches = list(response.context['pitches'])
        self.assertIn(open_pitch, pitches)
        self.assertEqual(len(pitches), 1)


@FAST_PASSWORD_HASHERS
class PitchDecisionTests(TestCase):
    def setUp(self):
        self.author = make_verified_author()
        self.editor = make_editor()
        self.pitch = StoryPitch.objects.create(
            title='A Story Worth Telling', summary='The pitch.', submitter=self.author,
        )
        self.client.force_login(self.editor)

    def test_start_review_updates_status_and_sends_email(self):
        self.client.post(reverse('pitches:manage_pitch_decide', args=[self.pitch.pk, 'start_review']))
        self.pitch.refresh_from_db()
        self.assertEqual(self.pitch.status, StoryPitch.Status.IN_REVIEW)
        self.assertEqual(self.pitch.reviewed_by, self.editor)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.author.email, mail.outbox[0].to)

    def test_reject_updates_status_and_sends_email(self):
        self.client.post(reverse('pitches:manage_pitch_decide', args=[self.pitch.pk, 'reject']))
        self.pitch.refresh_from_db()
        self.assertEqual(self.pitch.status, StoryPitch.Status.REJECTED)
        self.assertIsNotNone(self.pitch.decided_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_accept_creates_draft_article_and_links_it(self):
        response = self.client.post(reverse('pitches:manage_pitch_decide', args=[self.pitch.pk, 'accept']))
        self.pitch.refresh_from_db()
        self.assertEqual(self.pitch.status, StoryPitch.Status.ACCEPTED)
        self.assertIsNotNone(self.pitch.article)
        article = self.pitch.article
        self.assertEqual(article.title, self.pitch.title)
        self.assertEqual(article.abstract, self.pitch.summary)
        self.assertEqual(article.status, Article.Status.DRAFT)
        self.assertTrue(ArticleAuthor.objects.filter(article=article, user=self.author, is_corresponding=True).exists())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    def test_invalid_decision_is_rejected(self):
        response = self.client.post(reverse('pitches:manage_pitch_decide', args=[self.pitch.pk, 'not-a-real-decision']))
        self.assertEqual(response.status_code, 403)

    def test_verified_author_cannot_decide(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('pitches:manage_pitch_decide', args=[self.pitch.pk, 'accept']))
        self.assertEqual(response.status_code, 403)
        self.pitch.refresh_from_db()
        self.assertEqual(self.pitch.status, StoryPitch.Status.SUBMITTED)


@FAST_PASSWORD_HASHERS
class PitchArticlePublishSyncTests(TestCase):
    def test_pitch_status_becomes_published_when_linked_article_is_published(self):
        author = make_verified_author()
        editor = make_editor()
        pitch = StoryPitch.objects.create(title='Synced Story', summary='s', submitter=author)
        self.client.force_login(editor)
        self.client.post(reverse('pitches:manage_pitch_decide', args=[pitch.pk, 'accept']))
        pitch.refresh_from_db()
        article = pitch.article

        article.status = Article.Status.PUBLISHED
        article.save()

        pitch.refresh_from_db()
        self.assertEqual(pitch.status, StoryPitch.Status.PUBLISHED)
