from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from users.models import User

from .models import NewsletterIssue, Subscriber
from .tasks import send_newsletter_issue


class SubscribeFlowTests(TestCase):
    def test_subscribe_creates_pending_subscriber_and_sends_confirmation_email(self):
        response = self.client.post(reverse('newsletter:subscribe'), {'email': 'reader@example.com'})
        self.assertEqual(response.status_code, 302)
        subscriber = Subscriber.objects.get(email='reader@example.com')
        self.assertEqual(subscriber.status, Subscriber.Status.PENDING)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(subscriber.confirm_token, mail.outbox[0].body)

    def test_honeypot_blocks_without_creating_subscriber(self):
        self.client.post(reverse('newsletter:subscribe'), {'email': 'bot@example.com', 'website': 'http://spam.example'})
        self.assertFalse(Subscriber.objects.filter(email='bot@example.com').exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_confirm_marks_subscriber_confirmed(self):
        subscriber = Subscriber.objects.create(email='confirm@example.com')
        response = self.client.get(reverse('newsletter:confirm', args=[subscriber.confirm_token]))
        self.assertEqual(response.status_code, 200)
        subscriber.refresh_from_db()
        self.assertEqual(subscriber.status, Subscriber.Status.CONFIRMED)
        self.assertIsNotNone(subscriber.confirmed_at)

    def test_unsubscribe_marks_subscriber_unsubscribed(self):
        subscriber = Subscriber.objects.create(email='unsub@example.com', status=Subscriber.Status.CONFIRMED)
        response = self.client.get(reverse('newsletter:unsubscribe', args=[subscriber.unsubscribe_token]))
        self.assertEqual(response.status_code, 200)
        subscriber.refresh_from_db()
        self.assertEqual(subscriber.status, Subscriber.Status.UNSUBSCRIBED)
        self.assertIsNotNone(subscriber.unsubscribed_at)


class SendNewsletterIssueTaskTests(TestCase):
    """Unit-tests the background task function directly — no worker process
    needed since this just calls the function, same as django_q would.
    """

    def test_emails_only_confirmed_subscribers(self):
        Subscriber.objects.create(email='confirmed@example.com', status=Subscriber.Status.CONFIRMED)
        Subscriber.objects.create(email='pending@example.com', status=Subscriber.Status.PENDING)
        Subscriber.objects.create(email='unsubscribed@example.com', status=Subscriber.Status.UNSUBSCRIBED)
        issue = NewsletterIssue.objects.create(subject='Weekly Digest', body_html='<p>News</p>')

        sent = send_newsletter_issue(issue.pk)

        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['confirmed@example.com'])
        issue.refresh_from_db()
        self.assertIsNotNone(issue.sent_at)
        self.assertEqual(issue.recipient_count, 1)


class ComposeViewTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )

    @patch('newsletter.views.async_task')
    def test_compose_triggers_async_send(self, mock_async_task):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('newsletter:manage_issue_compose'), {
            'subject': 'Hello', 'body_html': '<p>Hi</p>',
        })
        self.assertEqual(response.status_code, 302)
        issue = NewsletterIssue.objects.get(subject='Hello')
        mock_async_task.assert_called_once_with('newsletter.tasks.send_newsletter_issue', issue.pk)

    def test_non_editorial_cannot_compose(self):
        reader = User.objects.create_user(email='reader3@example.com', password='pw', first_name='R', last_name='D')
        self.client.force_login(reader)
        response = self.client.post(reverse('newsletter:manage_issue_compose'), {
            'subject': 'Hello', 'body_html': '<p>Hi</p>',
        })
        self.assertEqual(response.status_code, 403)
