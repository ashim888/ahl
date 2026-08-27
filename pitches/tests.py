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
        reader = User.objects.create_user(email='reader@example.com', password='pw', first_name='R', last_name='D')
        self.assertEqual(reader.role, User.Role.UNVERIFIED)
        self.client.force_login(reader)
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertEqual(response.status_code, 200)

    def test_editorial_staff_can_also_submit(self):
        self.client.force_login(make_editor())
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertEqual(response.status_code, 200)

    def test_anonymous_visitor_can_view_and_submit(self):
        # Revised August 2026: no login required at all — see
        # pitches/views.py PitchCreateView. Anyone can pitch a story;
        # CAPTCHA (pitches/captcha.py) is the actual bot mitigation now,
        # not a login gate.
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertEqual(response.status_code, 200)


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

    def test_submitting_notifies_senior_editorial_staff(self):
        eic = User.objects.create_user(
            email='pitch-notify-eic@example.com', password='pw', first_name='E', last_name='C', role=User.Role.EDITOR_IN_CHIEF,
        )
        mail.outbox = []
        self.client.post(reverse('pitches:pitch_create'), {
            'title': 'A Notify-Worthy Pitch', 'summary': 'Why this matters now.', 'body': '',
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(eic.email, mail.outbox[0].to)
        self.assertIn('A Notify-Worthy Pitch', mail.outbox[0].subject)

    def test_logged_in_submitter_is_not_asked_for_contact_info(self):
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertNotContains(response, 'name="submitter_name"')
        self.assertNotContains(response, 'name="submitter_email"')

    def test_honeypot_blocks_submission(self):
        self.client.post(reverse('pitches:pitch_create'), {
            'title': 'Spam Pitch', 'summary': 'x', 'website': 'http://spam.example',
        })
        self.assertFalse(StoryPitch.objects.filter(title='Spam Pitch').exists())

    def test_excessive_submissions_are_rate_limited(self):
        # Limit is 10/h by IP now (pitches/views.py PitchCreateView /
        # ratelimit) — keyed on IP, not user, since submission no longer
        # requires an account.
        for i in range(10):
            self.client.post(reverse('pitches:pitch_create'), {'title': f'Pitch {i}', 'summary': 'x'})
        response = self.client.post(reverse('pitches:pitch_create'), {'title': 'Pitch overflow', 'summary': 'x'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(StoryPitch.objects.filter(title='Pitch overflow').exists())


@FAST_PASSWORD_HASHERS
class AnonymousPitchSubmissionTests(TestCase):
    """No account at all — the actual point of this revision: anyone can
    pitch, and their contact info is captured directly on the pitch
    (StoryPitch.submitter_name/submitter_email) so the editorial team can
    still follow up or credit them, even though there's no User row to link.
    """

    def test_submitting_creates_pitch_with_no_submitter_account(self):
        response = self.client.post(reverse('pitches:pitch_create'), {
            'title': 'Guest Pitch', 'summary': 'An idea worth covering.',
            'submitter_name': 'Jane Guest', 'submitter_email': 'jane.guest@example.com',
        })
        self.assertEqual(response.status_code, 302)
        pitch = StoryPitch.objects.get(title='Guest Pitch')
        self.assertIsNone(pitch.submitter)
        self.assertEqual(pitch.contact_name, 'Jane Guest')
        self.assertEqual(pitch.contact_email, 'jane.guest@example.com')

    def test_missing_name_is_rejected(self):
        response = self.client.post(reverse('pitches:pitch_create'), {
            'title': 'No Name', 'summary': 'x', 'submitter_email': 'noname@example.com',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StoryPitch.objects.filter(title='No Name').exists())

    def test_missing_email_is_rejected(self):
        response = self.client.post(reverse('pitches:pitch_create'), {
            'title': 'No Email', 'summary': 'x', 'submitter_name': 'No Email Guest',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StoryPitch.objects.filter(title='No Email').exists())

    def test_anonymous_redirect_goes_to_homepage_not_my_pitches(self):
        # An anonymous submitter has no account to view pitches:my_pitches
        # with — the confirmation message is their only feedback.
        response = self.client.post(reverse('pitches:pitch_create'), {
            'title': 'Redirect Check', 'summary': 'x',
            'submitter_name': 'Guest', 'submitter_email': 'redirect-check@example.com',
        })
        self.assertRedirects(response, reverse('articles:home'))

    def test_anonymous_form_shows_contact_fields(self):
        response = self.client.get(reverse('pitches:pitch_create'))
        self.assertContains(response, 'name="submitter_name"')
        self.assertContains(response, 'name="submitter_email"')


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

    def test_open_pitches_show_direct_accept_reject_actions(self):
        author = make_verified_author()
        pitch = StoryPitch.objects.create(title='Open', summary='s', submitter=author, status=StoryPitch.Status.SUBMITTED)

        self.client.force_login(make_editor())
        response = self.client.get(reverse('pitches:manage_pitch_queue'))
        self.assertContains(response, reverse('pitches:manage_pitch_decide', args=[pitch.pk, 'accept']))
        self.assertContains(response, reverse('pitches:manage_pitch_decide', args=[pitch.pk, 'reject']))

    def test_decided_pitches_hide_accept_reject_actions(self):
        author = make_verified_author()
        pitch = StoryPitch.objects.create(title='Rejected', summary='s', submitter=author, status=StoryPitch.Status.REJECTED)

        self.client.force_login(make_editor())
        response = self.client.get(reverse('pitches:manage_pitch_queue'), {'status': StoryPitch.Status.REJECTED})
        self.assertNotContains(response, reverse('pitches:manage_pitch_decide', args=[pitch.pk, 'accept']))

    def test_search_filters_by_title(self):
        author = make_verified_author()
        match = StoryPitch.objects.create(title='Vaccine Rollout Delays', summary='s', submitter=author)
        StoryPitch.objects.create(title='Unrelated Pitch', summary='s', submitter=author)

        self.client.force_login(make_editor())
        response = self.client.get(reverse('pitches:manage_pitch_queue'), {'q': 'vaccine'})
        self.assertEqual(list(response.context['pitches']), [match])

    def test_search_filters_by_contact_email(self):
        match = StoryPitch.objects.create(
            title='Anon Pitch', summary='s', submitter_name='Guest', submitter_email='findme@example.com',
        )
        StoryPitch.objects.create(title='Other Pitch', summary='s', submitter_name='Guest', submitter_email='other@example.com')

        self.client.force_login(make_editor())
        response = self.client.get(reverse('pitches:manage_pitch_queue'), {'q': 'findme'})
        self.assertEqual(list(response.context['pitches']), [match])


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

    def test_accepting_a_pitch_with_script_in_body_does_not_create_executable_html(self):
        # pitch.body is public, low-trust input (any account, or anonymous —
        # see StoryPitch's docstring); Article.html_content is documented as
        # trusted HTML rendered unescaped. A malicious body must not survive
        # the trip into html_content as a live <script> tag.
        malicious_pitch = StoryPitch.objects.create(
            title='Malicious Pitch', summary='s', submitter=self.author,
            body='<script>alert(document.cookie)</script>',
        )
        self.client.post(reverse('pitches:manage_pitch_decide', args=[malicious_pitch.pk, 'accept']))
        malicious_pitch.refresh_from_db()
        self.assertNotIn('<script>', malicious_pitch.article.html_content)
        self.assertIn('&lt;script&gt;', malicious_pitch.article.html_content)

    def test_invalid_decision_is_rejected(self):
        response = self.client.post(reverse('pitches:manage_pitch_decide', args=[self.pitch.pk, 'not-a-real-decision']))
        self.assertEqual(response.status_code, 403)

    def test_verified_author_cannot_decide(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('pitches:manage_pitch_decide', args=[self.pitch.pk, 'accept']))
        self.assertEqual(response.status_code, 403)
        self.pitch.refresh_from_db()
        self.assertEqual(self.pitch.status, StoryPitch.Status.SUBMITTED)

    def test_accepting_an_anonymous_pitch_creates_no_byline(self):
        # No submitter account to link — an editor adds authorship by hand
        # later if they follow up with the guest via pitch.contact_email.
        anon_pitch = StoryPitch.objects.create(
            title='Guest Idea', summary='s', submitter_name='Guest', submitter_email='guest@example.com',
        )
        response = self.client.post(reverse('pitches:manage_pitch_decide', args=[anon_pitch.pk, 'accept']))
        self.assertEqual(response.status_code, 302)
        anon_pitch.refresh_from_db()
        self.assertIsNotNone(anon_pitch.article)
        self.assertFalse(ArticleAuthor.objects.filter(article=anon_pitch.article).exists())

    def test_status_change_email_goes_to_anonymous_contact_email(self):
        anon_pitch = StoryPitch.objects.create(
            title='Guest Idea', summary='s', submitter_name='Guest', submitter_email='guest-email@example.com',
        )
        self.client.post(reverse('pitches:manage_pitch_decide', args=[anon_pitch.pk, 'reject']))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('guest-email@example.com', mail.outbox[0].to)


@FAST_PASSWORD_HASHERS
class PitchBulkDecisionTests(TestCase):
    def setUp(self):
        self.author = make_verified_author()
        self.editor = make_editor()
        self.pitch_a = StoryPitch.objects.create(title='Pitch A', summary='s', submitter=self.author)
        self.pitch_b = StoryPitch.objects.create(title='Pitch B', summary='s', submitter=self.author)
        self.client.force_login(self.editor)

    def test_bulk_reject_rejects_all_selected(self):
        self.client.post(reverse('pitches:manage_pitch_bulk_decide'), {
            'decision': 'reject', 'pks': [self.pitch_a.pk, self.pitch_b.pk],
        })
        self.pitch_a.refresh_from_db()
        self.pitch_b.refresh_from_db()
        self.assertEqual(self.pitch_a.status, StoryPitch.Status.REJECTED)
        self.assertEqual(self.pitch_b.status, StoryPitch.Status.REJECTED)
        self.assertEqual(len(mail.outbox), 2)

    def test_bulk_accept_creates_a_draft_article_per_pitch(self):
        self.client.post(reverse('pitches:manage_pitch_bulk_decide'), {
            'decision': 'accept', 'pks': [self.pitch_a.pk, self.pitch_b.pk],
        })
        self.pitch_a.refresh_from_db()
        self.pitch_b.refresh_from_db()
        self.assertEqual(self.pitch_a.status, StoryPitch.Status.ACCEPTED)
        self.assertEqual(self.pitch_b.status, StoryPitch.Status.ACCEPTED)
        self.assertIsNotNone(self.pitch_a.article)
        self.assertIsNotNone(self.pitch_b.article)
        self.assertNotEqual(self.pitch_a.article_id, self.pitch_b.article_id)

    def test_bulk_accepting_a_pitch_with_script_in_body_does_not_create_executable_html(self):
        malicious_pitch = StoryPitch.objects.create(
            title='Malicious Pitch', summary='s', submitter=self.author,
            body='<script>alert(document.cookie)</script>',
        )
        self.client.post(reverse('pitches:manage_pitch_bulk_decide'), {
            'decision': 'accept', 'pks': [malicious_pitch.pk],
        })
        malicious_pitch.refresh_from_db()
        self.assertNotIn('<script>', malicious_pitch.article.html_content)
        self.assertIn('&lt;script&gt;', malicious_pitch.article.html_content)

    def test_already_decided_pitches_are_skipped(self):
        self.pitch_a.status = StoryPitch.Status.REJECTED
        self.pitch_a.save()
        response = self.client.post(reverse('pitches:manage_pitch_bulk_decide'), {
            'decision': 'accept', 'pks': [self.pitch_a.pk, self.pitch_b.pk],
        })
        self.assertRedirects(response, reverse('pitches:manage_pitch_queue'))
        self.pitch_a.refresh_from_db()
        self.pitch_b.refresh_from_db()
        self.assertEqual(self.pitch_a.status, StoryPitch.Status.REJECTED)
        self.assertIsNone(self.pitch_a.article)
        self.assertEqual(self.pitch_b.status, StoryPitch.Status.ACCEPTED)

    def test_invalid_decision_is_rejected(self):
        response = self.client.post(reverse('pitches:manage_pitch_bulk_decide'), {
            'decision': 'not-a-real-decision', 'pks': [self.pitch_a.pk],
        })
        self.assertEqual(response.status_code, 403)

    def test_verified_author_cannot_bulk_decide(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('pitches:manage_pitch_bulk_decide'), {
            'decision': 'reject', 'pks': [self.pitch_a.pk],
        })
        self.assertEqual(response.status_code, 403)
        self.pitch_a.refresh_from_db()
        self.assertEqual(self.pitch_a.status, StoryPitch.Status.SUBMITTED)


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


class PitchDiscoverabilityTests(TestCase):
    """"Pitch a Story" is a top-level public nav item (templates/base.html)
    and a homepage banner (templates/home.html) — both unconditional now
    that submission itself has no login requirement, so every visitor sees
    the same entry point regardless of account state.
    """

    def test_nav_pitch_link_shown_to_anonymous_visitors(self):
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, reverse('pitches:pitch_create'))
        self.assertContains(response, 'GOT A STORY')

    def test_nav_pitch_link_shown_to_logged_in_users_too(self):
        author = make_verified_author()
        self.client.force_login(author)
        response = self.client.get(reverse('articles:home'))
        self.assertContains(response, reverse('pitches:pitch_create'))


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
