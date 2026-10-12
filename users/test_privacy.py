"""Privacy rights: data download, account deletion (self-service and by
staff), email preferences and one-click unsubscribe, cookie consent,
consent at sign-up, and the daily retention clean-up."""
import datetime
import json

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_comments_xtd.models import XtdComment

from articles.models import Article, Author, Bookmark
from billing import payments
from billing.models import Payment, SubscriptionPlan, UserSubscription
from newsletter.models import Subscriber
from pitches.models import StoryPitch
from sections.models import Section, SectionFollow

from . import privacy
from .models import User
from .tests import FAST_PASSWORD_HASHERS


def make_user(email='reader@example.com', role=User.Role.UNVERIFIED, password='Kathmandu-2026!', **extra):
    return User.objects.create_user(email=email, password=password, first_name='Maya', last_name='Thapa', role=role, **extra)


def comment_on(article, *, user=None, name='Maya', email='reader@example.com', ip='203.0.113.7', when=None):
    return XtdComment.objects.create(
        content_type=ContentType.objects.get_for_model(Article), object_pk=str(article.pk), site_id=settings.SITE_ID,
        user=user, user_name=name, user_email=email, comment='Useful piece.', ip_address=ip,
        submit_date=when or timezone.now(), is_public=True,
    )


@FAST_PASSWORD_HASHERS
class DataExportTests(TestCase):
    def setUp(self):
        self.reader = make_user()
        self.article = Article.objects.create(title='Saved story', slug='saved-story', status=Article.Status.PUBLISHED)
        Bookmark.objects.create(user=self.reader, article=self.article)
        comment_on(self.article, user=self.reader)
        make_user('someone-else@example.com')

    def test_download_contains_my_data_and_nobody_elses(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse('users:privacy_export'))
        self.assertEqual(response['Content-Type'], 'application/json; charset=utf-8')
        self.assertIn('attachment; filename="my-data-', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        data = json.loads(response.content)
        self.assertEqual(data['account']['email'], 'reader@example.com')
        self.assertEqual(data['saved_articles'][0]['title'], 'Saved story')
        self.assertEqual(data['comments'][0]['comment'], 'Useful piece.')
        self.assertNotIn('someone-else', response.content.decode())

    def test_needs_sign_in(self):
        self.assertEqual(self.client.get(reverse('users:privacy_export')).status_code, 302)


@FAST_PASSWORD_HASHERS
class SelfServiceDeletionTests(TestCase):
    def setUp(self):
        self.reader = make_user()
        self.article = Article.objects.create(title='Story', slug='erase-story', status=Article.Status.PUBLISHED)
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        self.payment = payments.record_paid_payment(
            user=self.reader, kind=Payment.Kind.SUBSCRIPTION, plan=self.plan, price=499, description='Subscription',
            gateway=Payment.Gateway.STUB,
        )
        Bookmark.objects.create(user=self.reader, article=self.article)
        SectionFollow.objects.create(user=self.reader, section=Section.objects.first())
        Subscriber.objects.create(email='reader@example.com', status=Subscriber.Status.CONFIRMED)
        self.comment = comment_on(self.article, user=self.reader)
        self.author = Author.objects.create(name='Maya Thapa', email='reader@example.com', user=self.reader)
        self.accepted = StoryPitch.objects.create(
            title='Accepted', summary='x', submitter=self.reader, submitter_name='Maya', submitter_email='reader@example.com',
            status=StoryPitch.Status.ACCEPTED,
        )
        StoryPitch.objects.create(title='Pending', summary='x', submitter=self.reader, status=StoryPitch.Status.SUBMITTED)
        self.client.force_login(self.reader)

    def _delete(self, **data):
        payload = {'password': 'Kathmandu-2026!', 'understood': 'on'}
        payload.update(data)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('users:privacy_delete'), payload)

    def test_wrong_password_or_no_tick_deletes_nothing(self):
        self._delete(password='wrong')
        self._delete(understood='')
        self.reader.refresh_from_db()
        self.assertIsNone(self.reader.erased_at)
        self.assertTrue(self.reader.is_active)

    def test_deletion_removes_personal_data_and_keeps_records(self):
        response = self._delete()
        self.assertContains(response, 'Your account has been deleted')
        self.reader.refresh_from_db()
        self.assertIsNotNone(self.reader.erased_at)
        self.assertFalse(self.reader.is_active)
        self.assertFalse(self.reader.has_usable_password())
        self.assertEqual(self.reader.email, f'deleted-{self.reader.pk}@deleted.invalid')
        self.assertEqual(self.reader.first_name, privacy.ERASED_NAME)
        # Personal things: gone.
        self.assertFalse(Bookmark.objects.exists())
        self.assertFalse(SectionFollow.objects.exists())
        self.assertFalse(Subscriber.objects.exists())
        self.assertEqual(list(StoryPitch.objects.values_list('title', flat=True)), ['Accepted'])
        # Records: kept, anonymised.
        self.comment.refresh_from_db()
        self.assertEqual((self.comment.user_name, self.comment.user_email, self.comment.ip_address), (privacy.ERASED_NAME, '', None))
        self.assertFalse(self.comment.is_removed)
        self.accepted.refresh_from_db()
        self.assertEqual((self.accepted.submitter_name, self.accepted.submitter_email), (privacy.ERASED_NAME, ''))
        self.author.refresh_from_db()
        self.assertEqual((self.author.user, self.author.email, self.author.name), (None, '', 'Maya Thapa'))
        # Paid access ends; the receipt still names who paid.
        self.assertEqual(UserSubscription.objects.get().status, UserSubscription.Status.CANCELLED)
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.payer_name, self.payment.payer_email), ('Maya Thapa', 'reader@example.com'))
        # A last email to the old address, and signed out.
        self.assertEqual(mail.outbox[-1].to, ['reader@example.com'])
        self.assertIn('has been deleted', mail.outbox[-1].subject)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_can_also_remove_comments(self):
        self._delete(remove_comments='on')
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.is_removed)

    def test_invited_account_without_password_confirms_with_email(self):
        invited = make_user('invited-delete@example.com', password=None)
        self.client.force_login(invited)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('users:privacy_delete'), {'email_confirm': 'INVITED-delete@example.com', 'understood': 'on'})
        invited.refresh_from_db()
        self.assertIsNotNone(invited.erased_at)

    def test_staff_cannot_delete_themselves_here(self):
        editor = make_user('editor-delete@example.com', role=User.Role.EDITOR)
        self.client.force_login(editor)
        self.assertNotContains(self.client.get(reverse('users:privacy')), 'DELETE MY ACCOUNT')
        self._delete()
        editor.refresh_from_db()
        self.assertIsNone(editor.erased_at)

    def test_sign_in_records_for_the_email_are_removed(self):
        from axes.models import AccessAttempt

        AccessAttempt.objects.create(username='reader@example.com', ip_address='203.0.113.9', user_agent='x', failures_since_start=1)
        self._delete()
        self.assertFalse(AccessAttempt.objects.filter(username='reader@example.com').exists())


@FAST_PASSWORD_HASHERS
class StaffErasureTests(TestCase):
    def setUp(self):
        self.eic = make_user('eic-erase@example.com', role=User.Role.EDITOR_IN_CHIEF)
        self.reader = make_user('asked-by-email@example.com')
        self.url = reverse('users:manage_account_erase', args=[self.reader.pk])

    def test_eic_erases_after_typing_the_email(self):
        self.client.force_login(self.eic)
        self.assertContains(self.client.get(reverse('users:manage_account_update', args=[self.reader.pk])), 'Delete personal data')
        self.client.post(self.url, {'confirm_email': 'wrong@example.com'})
        self.reader.refresh_from_db()
        self.assertIsNone(self.reader.erased_at)
        self.client.post(self.url, {'confirm_email': 'asked-by-email@example.com'})
        self.reader.refresh_from_db()
        self.assertIsNotNone(self.reader.erased_at)

    def test_editors_cannot_erase(self):
        self.client.force_login(make_user('editor-erase@example.com', role=User.Role.EDITOR))
        self.assertEqual(self.client.post(self.url, {'confirm_email': 'asked-by-email@example.com'}).status_code, 403)

    def test_staff_accounts_must_be_demoted_first(self):
        editor = make_user('editor-target@example.com', role=User.Role.EDITOR)
        self.client.force_login(self.eic)
        self.client.post(reverse('users:manage_account_erase', args=[editor.pk]), {'confirm_email': 'editor-target@example.com'})
        editor.refresh_from_db()
        self.assertIsNone(editor.erased_at)


@FAST_PASSWORD_HASHERS
class EmailPreferenceTests(TestCase):
    def setUp(self):
        self.reader = make_user()

    def test_preferences_saved_from_the_privacy_page(self):
        self.client.force_login(self.reader)
        self.client.post(reverse('users:privacy'), {'action': 'emails', 'email_renewal_reminders': 'on'})
        self.reader.refresh_from_db()
        self.assertEqual((self.reader.email_topic_digest, self.reader.email_renewal_reminders), (False, True))

    def test_unsubscribe_link_asks_first_then_switches_off(self):
        url = privacy.unsubscribe_url(self.reader, 'digest').removeprefix(settings.SITE_BASE_URL)
        page = self.client.get(url)
        self.assertContains(page, 'the weekly digest of topics you follow')
        self.reader.refresh_from_db()
        self.assertTrue(self.reader.email_topic_digest)  # a mail scanner opening the link changes nothing
        self.client.post(url)
        self.reader.refresh_from_db()
        self.assertFalse(self.reader.email_topic_digest)

    def test_one_click_works_without_a_session_or_csrf(self):
        from django.test import Client

        url = privacy.unsubscribe_url(self.reader, 'reminders').removeprefix(settings.SITE_BASE_URL)
        Client(enforce_csrf_checks=True).post(url, {'List-Unsubscribe': 'One-Click'})
        self.reader.refresh_from_db()
        self.assertFalse(self.reader.email_renewal_reminders)

    def test_tampered_link_is_refused(self):
        url = privacy.unsubscribe_url(self.reader, 'digest').removeprefix(settings.SITE_BASE_URL)
        self.assertEqual(self.client.post(url[:-4] + 'xyz/').status_code, 400)

    def test_digest_respects_the_preference_and_has_one_click_headers(self):
        from articles.models import Keyword, KeywordFollow
        from sections.digest import send_topic_digests

        keyword = Keyword.objects.create(name='Malaria')
        article = Article.objects.create(
            title='Malaria update', slug='malaria-update', status=Article.Status.PUBLISHED,
            publication_date=timezone.localdate(),
        )
        article.keyword_tags.add(keyword)
        KeywordFollow.objects.create(user=self.reader, keyword=keyword)
        self.assertEqual(send_topic_digests(), 1)
        self.assertIn('List-Unsubscribe', mail.outbox[-1].extra_headers)
        self.assertIn('Stop this weekly digest:', mail.outbox[-1].body)
        User.objects.filter(pk=self.reader.pk).update(email_topic_digest=False)
        self.assertEqual(send_topic_digests(), 0)

    def test_reminders_respect_the_preference_and_carry_the_link(self):
        from billing.reminders import send_subscription_reminders

        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(user=self.reader, plan=plan, start_date=today - datetime.timedelta(days=23),
                                        end_date=today + datetime.timedelta(days=7))
        User.objects.filter(pk=self.reader.pk).update(email_renewal_reminders=False)
        self.assertEqual(send_subscription_reminders(), 0)
        User.objects.filter(pk=self.reader.pk).update(email_renewal_reminders=True)
        self.assertEqual(send_subscription_reminders(), 1)
        self.assertIn('List-Unsubscribe-Post', mail.outbox[-1].extra_headers)
        self.assertIn('Stop renewal reminders:', mail.outbox[-1].body)

    def test_newsletter_unsubscribe_accepts_one_click_post(self):
        from django.test import Client

        subscriber = Subscriber.objects.create(email='news@example.com', status=Subscriber.Status.CONFIRMED)
        Client(enforce_csrf_checks=True).post(reverse('newsletter:unsubscribe', args=[subscriber.unsubscribe_token]))
        subscriber.refresh_from_db()
        self.assertEqual(subscriber.status, Subscriber.Status.UNSUBSCRIBED)


@override_settings(GOOGLE_ANALYTICS_ID='G-TEST123')
class CookieConsentTests(TestCase):
    def test_no_analytics_until_accepted(self):
        page = self.client.get(reverse('articles:home'))
        self.assertNotContains(page, 'googletagmanager.com/gtag/js?id=G-TEST123"')
        self.assertContains(page, 'id="cookie-consent"')
        self.assertNotContains(page, 'class="hidden fixed inset-x-0')

    def test_accepted_loads_analytics_and_hides_banner(self):
        self.client.cookies['cookie_consent'] = 'v1:analytics'
        page = self.client.get(reverse('articles:home'))
        self.assertContains(page, 'googletagmanager.com/gtag/js?id=G-TEST123"')
        self.assertContains(page, 'class="hidden fixed inset-x-0')

    def test_only_essential_never_loads_analytics(self):
        self.client.cookies['cookie_consent'] = 'v1:essential'
        page = self.client.get(reverse('articles:home'))
        self.assertNotContains(page, 'googletagmanager.com/gtag/js?id=G-TEST123"')
        self.assertContains(page, 'data-cookie-settings')

    @override_settings(GOOGLE_ANALYTICS_ID='')
    def test_no_id_no_analytics_even_with_consent(self):
        self.client.cookies['cookie_consent'] = 'v1:analytics'
        self.assertNotContains(self.client.get(reverse('articles:home')), '<script async src="https://www.googletagmanager.com')


@FAST_PASSWORD_HASHERS
class SignupConsentTests(TestCase):
    DATA = {'first_name': 'Asha', 'last_name': 'Rai', 'email': 'asha@example.com',
            'password1': 'Kathmandu-2026!', 'password2': 'Kathmandu-2026!'}

    def setUp(self):
        cache.clear()

    def test_no_checkbox_while_the_pages_are_drafts(self):
        self.assertNotContains(self.client.get(reverse('users:register')), 'accept_terms')
        self.client.post(reverse('users:register'), self.DATA)
        self.assertIsNone(User.objects.get(email='asha@example.com').terms_accepted_at)

    def test_published_terms_must_be_accepted_and_it_is_recorded(self):
        from pages.models import SitePage

        for page in SitePage.objects.filter(slug__in=['terms', 'privacy']):
            page.is_published = True
            page.save()
        form = self.client.get(reverse('users:register'))
        self.assertContains(form, 'name="accept_terms"')
        self.assertContains(form, 'href="/privacy/"')
        refused = self.client.post(reverse('users:register'), self.DATA)
        self.assertContains(refused, 'Please agree to the terms')
        self.assertFalse(User.objects.filter(email='asha@example.com').exists())
        self.client.post(reverse('users:register'), {**self.DATA, 'accept_terms': 'on'})
        self.assertIsNotNone(User.objects.get(email='asha@example.com').terms_accepted_at)


class RetentionHousekeepingTests(TestCase):
    def test_old_personal_data_is_cleared_on_schedule(self):
        from axes.models import AccessLog
        from django.contrib.sessions.backends.db import SessionStore
        from django.contrib.sessions.models import Session

        article = Article.objects.create(title='Old', slug='old-comments', status=Article.Status.PUBLISHED)
        old = comment_on(article, when=timezone.now() - datetime.timedelta(days=100))
        recent = comment_on(article)
        stale_log = AccessLog.objects.create(username='a@example.com', ip_address='203.0.113.1', user_agent='x')
        AccessLog.objects.filter(pk=stale_log.pk).update(attempt_time=timezone.now() - datetime.timedelta(days=100))
        AccessLog.objects.create(username='b@example.com', ip_address='203.0.113.2', user_agent='x')
        pending = Subscriber.objects.create(email='never-confirmed@example.com')
        Subscriber.objects.filter(pk=pending.pk).update(subscribed_at=timezone.now() - datetime.timedelta(days=40))
        Subscriber.objects.create(email='new@example.com')
        session = SessionStore()
        session.create()
        Session.objects.filter(session_key=session.session_key).update(expire_date=timezone.now() - datetime.timedelta(days=1))

        done = privacy.privacy_housekeeping()

        old.refresh_from_db()
        recent.refresh_from_db()
        self.assertIsNone(old.ip_address)
        self.assertEqual(recent.ip_address, '203.0.113.7')
        self.assertEqual(list(AccessLog.objects.values_list('username', flat=True)), ['b@example.com'])
        self.assertEqual(list(Subscriber.objects.values_list('email', flat=True)), ['new@example.com'])
        self.assertFalse(Session.objects.filter(session_key=session.session_key).exists())
        self.assertEqual(done['comment_ips_cleared'], 1)

    def test_runs_daily(self):
        from django_q.models import Schedule

        self.assertEqual(Schedule.objects.get(name='privacy_housekeeping_daily').func, 'users.privacy.privacy_housekeeping')


@override_settings(BUSINESS_LEGAL_NAME='Ajna Media Pvt. Ltd.', BUSINESS_PAN='600123456', BUSINESS_ADDRESS='Lalitpur, Nepal')
class FooterBusinessDetailsTests(TestCase):
    def test_footer_says_who_runs_the_site(self):
        page = self.client.get(reverse('articles:home'))
        self.assertContains(page, 'Ajna Media Pvt. Ltd.')
        self.assertContains(page, 'PAN 600123456')
        self.assertContains(page, 'Lalitpur, Nepal')
