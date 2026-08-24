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

    def test_unverified_user_can_submit(self):
        # The whole point of a lightweight pitch is that it's the low-barrier
        # way in — a brand-new, not-yet-verified account can use it without
        # first being trusted as an author.
        reader = User.objects.create_user(email='reader@example.com', password='pw', first_name='R', last_name='D')
        self.assertEqual(reader.role, User.Role.UNVERIFIED)
        self.client.force_login(reader)
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertEqual(response.status_code, 200)

    def test_editorial_staff_can_also_submit(self):
        # Revised August 2026: no role restriction at all, any authenticated
        # account may pitch — see pitches/views.py PitchCreateView.
        self.client.force_login(make_editor())
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertEqual(response.status_code, 200)

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
        # Limit is 10/h by user (pitches/views.py PitchCreateView / ratelimit).
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

    def test_filters_by_status(self):
        author = make_verified_author()
        submitted = StoryPitch.objects.create(
            title='Submitted', summary='s', submitter=author, status=StoryPitch.Status.SUBMITTED,
        )
        StoryPitch.objects.create(title='Rejected', summary='s', submitter=author, status=StoryPitch.Status.REJECTED)

        self.client.force_login(author)
        response = self.client.get(reverse('pitches:my_pitches'), {'status': StoryPitch.Status.SUBMITTED})
        self.assertEqual(list(response.context['pitches']), [submitted])


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


@FAST_PASSWORD_HASHERS
class PitchDiscoverabilityTests(TestCase):
    """The "Pitch a Story" nav link (templates/base.html, desktop + mobile)
    previously pointed at pitches:my_pitches (the list of a verified
    author's existing pitches) instead of pitches:pitch_create (the actual
    submit form) — a real author had no direct way in from the nav at all,
    only via the "+ New Pitch" button buried on that list page.
    """

    def test_nav_pitch_link_points_to_the_submit_form(self):
        author = make_verified_author()
        self.client.force_login(author)
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, reverse('pitches:pitch_create'))

    def test_nav_pitch_link_shown_to_unverified_readers_too(self):
        # Any authenticated account, not just already-verified authors.
        reader = User.objects.create_user(email='reader-nav@example.com', password='pw', first_name='R', last_name='D')
        self.assertEqual(reader.role, User.Role.UNVERIFIED)
        self.client.force_login(reader)
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, reverse('pitches:pitch_create'))

    def test_nav_pitch_link_shown_to_editorial_staff_too(self):
        # No role restriction at all now — see PitchSubmissionAccessTests.
        editor = make_editor()
        self.client.force_login(editor)
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, reverse('pitches:pitch_create'))

    def test_nav_pitch_link_hidden_for_anonymous_visitors(self):
        response = self.client.get(reverse('articles:home'))
        self.assertNotContains(response, reverse('pitches:pitch_create'))


class VerifyTurnstileTests(TestCase):
    """pitches/captcha.py:verify_turnstile — the actual bot-mitigation this
    now-open-to-anyone form relies on (see PitchSubmissionAccessTests).
    """

    def test_passes_when_secret_key_not_configured(self):
        from .captcha import verify_turnstile

        with override_settings(TURNSTILE_SECRET_KEY=''):
            self.assertTrue(verify_turnstile(''))
            self.assertTrue(verify_turnstile('anything'))

    @override_settings(TURNSTILE_SECRET_KEY='test-secret')
    def test_fails_with_no_token_once_configured(self):
        from .captcha import verify_turnstile

        self.assertFalse(verify_turnstile(''))

    @override_settings(TURNSTILE_SECRET_KEY='test-secret')
    def test_passes_when_cloudflare_reports_success(self):
        from unittest.mock import MagicMock, patch

        from .captcha import verify_turnstile

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"success": true}'
        mock_response.__enter__.return_value = mock_response
        with patch('pitches.captcha.urllib.request.urlopen', return_value=mock_response):
            self.assertTrue(verify_turnstile('a-real-looking-token'))

    @override_settings(TURNSTILE_SECRET_KEY='test-secret')
    def test_fails_when_cloudflare_reports_failure(self):
        from unittest.mock import MagicMock, patch

        from .captcha import verify_turnstile

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"success": false, "error-codes": ["invalid-input-response"]}'
        mock_response.__enter__.return_value = mock_response
        with patch('pitches.captcha.urllib.request.urlopen', return_value=mock_response):
            self.assertFalse(verify_turnstile('a-bad-token'))

    @override_settings(TURNSTILE_SECRET_KEY='test-secret')
    def test_fails_closed_on_network_error(self):
        import urllib.error
        from unittest.mock import patch

        from .captcha import verify_turnstile

        with patch('pitches.captcha.urllib.request.urlopen', side_effect=urllib.error.URLError('boom')):
            self.assertFalse(verify_turnstile('a-token'))


@FAST_PASSWORD_HASHERS
class PitchFormCaptchaTests(TestCase):
    """End-to-end through PitchCreateView, not just the helper function —
    proves the view/form actually wires cf-turnstile-response through to
    verify_turnstile rather than just importing it unused.
    """

    def setUp(self):
        self.author = make_verified_author()
        self.client.force_login(self.author)

    def test_submission_succeeds_without_captcha_by_default(self):
        # TURNSTILE_SECRET_KEY is blank in tests (no real keys yet) —
        # verify_turnstile short-circuits to True, matching every other
        # submission test in this file that never sends a token at all.
        response = self.client.post(reverse('pitches:pitch_create'), {
            'title': 'No Captcha Configured Yet', 'summary': 's',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(StoryPitch.objects.filter(title='No Captcha Configured Yet').exists())

    @override_settings(TURNSTILE_SECRET_KEY='test-secret')
    def test_submission_rejected_without_token_once_configured(self):
        response = self.client.post(reverse('pitches:pitch_create'), {
            'title': 'Missing Token', 'summary': 's',
        })
        self.assertEqual(response.status_code, 200)  # re-renders the form with an error, not a redirect
        self.assertFalse(StoryPitch.objects.filter(title='Missing Token').exists())

    @override_settings(TURNSTILE_SECRET_KEY='test-secret')
    def test_submission_succeeds_with_a_verified_token(self):
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"success": true}'
        mock_response.__enter__.return_value = mock_response
        with patch('pitches.captcha.urllib.request.urlopen', return_value=mock_response):
            response = self.client.post(reverse('pitches:pitch_create'), {
                'title': 'Verified Token', 'summary': 's', 'cf-turnstile-response': 'a-real-looking-token',
            })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(StoryPitch.objects.filter(title='Verified Token').exists())


class PitchFormWidgetRenderingTests(TestCase):
    def test_widget_hidden_when_no_site_key_configured(self):
        author = make_verified_author()
        self.client.force_login(author)
        with override_settings(TURNSTILE_SITE_KEY=''):
            response = self.client.get(reverse('pitches:pitch_create'))
        self.assertNotContains(response, 'cf-turnstile')

    def test_widget_shown_when_site_key_configured(self):
        author = make_verified_author('widget-author@example.com')
        self.client.force_login(author)
        with override_settings(TURNSTILE_SITE_KEY='test-site-key'):
            response = self.client.get(reverse('pitches:pitch_create'))
        self.assertContains(response, 'cf-turnstile')
        self.assertContains(response, 'test-site-key')
