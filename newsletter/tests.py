from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_q.models import Task

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
        mock_async_task.return_value = 'fake-task-id'
        self.client.force_login(self.editor)
        response = self.client.post(reverse('newsletter:manage_issue_compose'), {
            'subject': 'Hello', 'body_html': '<p>Hi</p>',
        })
        self.assertEqual(response.status_code, 302)
        issue = NewsletterIssue.objects.get(subject='Hello')
        mock_async_task.assert_called_once_with('newsletter.tasks.send_newsletter_issue', issue.pk)
        self.assertEqual(issue.task_id, 'fake-task-id')

    def test_non_editorial_cannot_compose(self):
        reader = User.objects.create_user(email='reader3@example.com', password='pw', first_name='R', last_name='D')
        self.client.force_login(reader)
        response = self.client.post(reverse('newsletter:manage_issue_compose'), {
            'subject': 'Hello', 'body_html': '<p>Hi</p>',
        })
        self.assertEqual(response.status_code, 403)


class IssuePreviewViewTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='newsletter-preview-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='newsletter-preview-reader@example.com', password='pw', first_name='R', last_name='D')

    def test_renders_subject_and_body_without_saving_or_sending(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('newsletter:manage_issue_preview'), {
            'subject': 'Preview Subject', 'body_html': '<p>Preview body content</p>',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Preview Subject')
        self.assertContains(response, 'Preview body content')
        self.assertContains(response, 'Preview only')
        self.assertFalse(NewsletterIssue.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_form_shows_errors_not_a_crash(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('newsletter:manage_issue_preview'), {'subject': '', 'body_html': ''})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'required', status_code=400)

    def test_non_editorial_cannot_preview(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('newsletter:manage_issue_preview'), {
            'subject': 'Hello', 'body_html': '<p>Hi</p>',
        })
        self.assertEqual(response.status_code, 403)


class IssueListFilterTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='newsletter-filter-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def test_filters_by_sent_status(self):
        sent = NewsletterIssue.objects.create(subject='Sent Issue', body_html='<p>Hi</p>', sent_at=timezone.now())
        NewsletterIssue.objects.create(subject='Sending Issue', body_html='<p>Hi</p>')

        response = self.client.get(reverse('newsletter:manage_issue_list'), {'status': 'sent'})
        self.assertEqual(list(response.context['issues']), [sent])

        response = self.client.get(reverse('newsletter:manage_issue_list'), {'status': 'sending'})
        issues = list(response.context['issues'])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].subject, 'Sending Issue')

    def test_filters_by_failed_status(self):
        failed_task = Task.objects.create(id='failed-task', name='t1', func='x', success=False, started=timezone.now(), stopped=timezone.now())
        failed = NewsletterIssue.objects.create(subject='Failed Issue', body_html='<p>Hi</p>', task_id=failed_task.id)
        # No matching Task row yet — still enqueued/running.
        NewsletterIssue.objects.create(subject='Sending Issue', body_html='<p>Hi</p>', task_id='not-finished-yet')

        response = self.client.get(reverse('newsletter:manage_issue_list'), {'status': 'failed'})
        self.assertEqual(list(response.context['issues']), [failed])

        response = self.client.get(reverse('newsletter:manage_issue_list'), {'status': 'sending'})
        issues = list(response.context['issues'])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].subject, 'Sending Issue')

    def test_search_filters_by_subject(self):
        match = NewsletterIssue.objects.create(subject='Weekly Digest', body_html='<p>Hi</p>')
        NewsletterIssue.objects.create(subject='Unrelated Issue', body_html='<p>Hi</p>')
        response = self.client.get(reverse('newsletter:manage_issue_list'), {'q': 'weekly'})
        self.assertEqual(list(response.context['issues']), [match])


class NewsletterIssueSendStatusTests(TestCase):
    def test_sent_status(self):
        issue = NewsletterIssue.objects.create(subject='S', body_html='<p>Hi</p>', sent_at=timezone.now())
        self.assertEqual(issue.get_send_status(), NewsletterIssue.Status.SENT)

    def test_sending_status_with_no_task_yet(self):
        issue = NewsletterIssue.objects.create(subject='S', body_html='<p>Hi</p>')
        self.assertEqual(issue.get_send_status(), NewsletterIssue.Status.SENDING)

    def test_sending_status_while_task_still_running(self):
        # django_q only inserts a Task row once a task *finishes* (success
        # or failure) — a still-running task has a task_id with no matching
        # row yet, not a row with success=None.
        issue = NewsletterIssue.objects.create(subject='S', body_html='<p>Hi</p>', task_id='not-finished-yet')
        self.assertEqual(issue.get_send_status(), NewsletterIssue.Status.SENDING)

    def test_failed_status_and_reason(self):
        task = Task.objects.create(id='failed-task-2', name='t', func='x', success=False, result='boom: SMTP timeout', started=timezone.now(), stopped=timezone.now())
        issue = NewsletterIssue.objects.create(subject='S', body_html='<p>Hi</p>', task_id=task.id)
        self.assertEqual(issue.get_send_status(), NewsletterIssue.Status.FAILED)
        self.assertEqual(issue.get_failure_reason(), 'boom: SMTP timeout')


class IssueRetryViewTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='newsletter-retry-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='newsletter-retry-reader@example.com', password='pw', first_name='R', last_name='D')

    @patch('newsletter.views.async_task')
    def test_editor_can_retry_failed_issue(self, mock_async_task):
        mock_async_task.return_value = 'retry-task-id'
        task = Task.objects.create(id='original-failed-task', name='t', func='x', success=False, started=timezone.now(), stopped=timezone.now())
        issue = NewsletterIssue.objects.create(subject='Retry Me', body_html='<p>Hi</p>', task_id=task.id)

        self.client.force_login(self.editor)
        response = self.client.post(reverse('newsletter:manage_issue_retry', args=[issue.pk]))
        self.assertRedirects(response, reverse('newsletter:manage_issue_list'))
        mock_async_task.assert_called_once_with('newsletter.tasks.send_newsletter_issue', issue.pk)
        issue.refresh_from_db()
        self.assertEqual(issue.task_id, 'retry-task-id')

    def test_cannot_retry_a_non_failed_issue(self):
        issue = NewsletterIssue.objects.create(subject='Already Sent', body_html='<p>Hi</p>', sent_at=timezone.now())
        self.client.force_login(self.editor)
        response = self.client.post(reverse('newsletter:manage_issue_retry', args=[issue.pk]))
        self.assertRedirects(response, reverse('newsletter:manage_issue_list'))

    def test_reader_cannot_retry(self):
        task = Task.objects.create(id='reader-blocked-task', name='t', func='x', success=False, started=timezone.now(), stopped=timezone.now())
        issue = NewsletterIssue.objects.create(subject='Retry Me', body_html='<p>Hi</p>', task_id=task.id)
        self.client.force_login(self.reader)
        response = self.client.post(reverse('newsletter:manage_issue_retry', args=[issue.pk]))
        self.assertEqual(response.status_code, 403)
