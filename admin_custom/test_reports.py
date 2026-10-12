"""Reader reports (admin_custom/reports.py), self-hosted fonts, and the
notify_users command used in INCIDENT_RESPONSE.md."""
import re
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_comments_xtd.models import XtdComment

from articles.models import Article
from users.models import User

from .models import ContentReport


def make_user(email, role=User.Role.UNVERIFIED, **extra):
    return User.objects.create_user(email=email, password='pw', first_name='Ram', last_name='Shah', role=role, **extra)


class ReportTests(TestCase):
    def setUp(self):
        self.eic = make_user('eic-reports@example.com', User.Role.EDITOR_IN_CHIEF)
        self.article = Article.objects.create(
            title='Vaccine schedule', slug='vaccine-schedule', status=Article.Status.PUBLISHED, html_content='<p>x</p>',
        )
        self.comment = XtdComment.objects.create(
            content_type=ContentType.objects.get_for_model(Article), object_pk=str(self.article.pk),
            site_id=settings.SITE_ID, user_name='Troll', user_email='troll@example.com', comment='Nasty words',
            submit_date=timezone.now(), is_public=True,
        )

    def test_report_links_on_the_article_and_each_comment(self):
        page = self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertContains(page, f'/report/?article={self.article.pk}')
        self.assertContains(page, f'/report/?comment={self.comment.pk}')

    def test_anonymous_reader_reports_a_comment_and_editors_are_emailed(self):
        response = self.client.post(reverse('report_content'), {
            'comment': self.comment.pk, 'reason': 'abuse', 'details': 'Insults another reader.', 'name': 'Sita',
        })
        self.assertContains(response, 'Thank you for telling us')
        report = ContentReport.objects.get()
        self.assertEqual((report.comment, report.article, report.reason), (self.comment, self.article, 'abuse'))
        self.assertIn('Troll', report.target_summary)
        self.assertEqual(report.target_url, f'{self.article.get_absolute_url()}#c{self.comment.pk}')
        self.assertIn('eic-reports@example.com', mail.outbox[-1].to)
        self.assertIn('Insults another reader.', mail.outbox[-1].body)

    def test_signed_in_reader_is_recorded_without_typing_details(self):
        reader = make_user('reporter@example.com')
        self.client.force_login(reader)
        form = self.client.get(reverse('report_content'), {'article': self.article.pk})
        self.assertNotContains(form, 'id="id_email"')
        self.client.post(reverse('report_content'), {'article': self.article.pk, 'reason': 'error', 'details': 'Wrong dose'})
        report = ContentReport.objects.get()
        self.assertEqual((report.reporter, report.reporter_email), (reader, 'reporter@example.com'))

    def test_copyright_and_privacy_claims_need_details_and_a_way_to_reply(self):
        response = self.client.post(reverse('report_content'), {'article': self.article.pk, 'reason': 'copyright'})
        self.assertContains(response, 'Please describe the problem')
        self.assertContains(response, 'We need a way to reach you')
        self.assertFalse(ContentReport.objects.exists())

    def test_bots_filling_the_hidden_field_are_ignored(self):
        self.client.post(reverse('report_content'), {'article': self.article.pk, 'reason': 'spam', 'website': 'spam.example'})
        self.assertFalse(ContentReport.objects.exists())

    def test_drafts_and_removed_comments_cannot_be_reported(self):
        draft = Article.objects.create(title='Draft', slug='draft-report', status=Article.Status.DRAFT)
        self.assertEqual(self.client.get(reverse('report_content'), {'article': draft.pk}).status_code, 404)
        XtdComment.objects.filter(pk=self.comment.pk).order_by().update(is_removed=True)
        self.assertEqual(self.client.get(reverse('report_content'), {'comment': self.comment.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse('report_content')).status_code, 404)

    def _report(self, **extra):
        data = {'comment': self.comment, 'article': self.article, 'target_summary': 'Comment by Troll', 'reason': 'abuse'}
        data.update(extra)
        return ContentReport.objects.create(**data)

    def test_editor_removes_the_comment_and_the_record_is_kept(self):
        report = self._report()
        self.client.force_login(make_user('editor-reports@example.com', User.Role.EDITOR))
        queue = self.client.get(reverse('admin_custom:manage_report_list'))
        self.assertContains(queue, 'Nasty words')
        self.client.post(reverse('admin_custom:manage_report_handle', args=[report.pk]), {'action': 'hide_comment', 'note': ''})
        report.refresh_from_db()
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.is_removed)
        self.assertEqual((report.status, report.resolution_note), (ContentReport.Status.RESOLVED, 'Comment removed.'))
        self.assertIsNotNone(report.handled_at)
        self.assertNotContains(self.client.get(reverse('admin_custom:manage_report_list')), 'Nasty words')
        self.assertContains(self.client.get(reverse('admin_custom:manage_report_list'), {'status': 'resolved'}), 'Comment removed.')

    def test_dismiss_and_reopen(self):
        report = self._report()
        self.client.force_login(self.eic)
        url = reverse('admin_custom:manage_report_handle', args=[report.pk])
        self.client.post(url, {'action': 'dismiss', 'note': 'Robust but fair.'})
        report.refresh_from_db()
        self.assertEqual(report.status, ContentReport.Status.DISMISSED)
        self.client.post(url, {'action': 'reopen'})
        report.refresh_from_db()
        self.assertEqual((report.status, report.handled_by), (ContentReport.Status.OPEN, None))

    def test_sidebar_counts_open_reports(self):
        self._report()
        self.client.force_login(self.eic)
        page = self.client.get(reverse('admin_custom:manage_report_list'))
        self.assertContains(page, 'title="Waiting for an editor">1<')

    def test_readers_cannot_see_or_handle_reports(self):
        report = self._report()
        self.client.force_login(make_user('nosy-reader@example.com'))
        self.assertEqual(self.client.get(reverse('admin_custom:manage_report_list')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('admin_custom:manage_report_handle', args=[report.pk]), {'action': 'dismiss'}).status_code, 403,
        )

    def test_report_survives_the_comment_being_deleted(self):
        report = self._report()
        self.comment.delete()
        report.refresh_from_db()
        self.assertEqual((report.comment, report.target_url), (None, self.article.get_absolute_url()))

    def test_deleting_the_reporters_account_anonymises_their_reports(self):
        from users import privacy

        reader = make_user('reporter-gone@example.com')
        report = self._report(reporter=reader, reporter_name='Ram Shah', reporter_email='reporter-gone@example.com')
        self.assertEqual(len(privacy.export_user_data(reader)['reports_sent']), 1)
        privacy.erase_user(reader)
        report.refresh_from_db()
        self.assertEqual((report.reporter, report.reporter_name, report.reporter_email), (None, '', ''))


class SelfHostedFontTests(TestCase):
    def test_no_request_goes_to_google_fonts(self):
        page = self.client.get(reverse('articles:home')).content.decode()
        self.assertNotIn('fonts.googleapis.com', page)
        self.assertNotIn('fonts.gstatic.com', page)
        self.assertIn('/static/css/fonts.css', page)

    def test_every_font_file_in_the_stylesheet_exists(self):
        static = Path(settings.BASE_DIR) / 'static'
        css = (static / 'css' / 'fonts.css').read_text()
        files = re.findall(r'url\(\.\./fonts/([^)]+)\)', css)
        self.assertGreaterEqual(len(files), 10)
        for name in files:
            self.assertTrue((static / 'fonts' / name).exists(), name)
        for family in ('Playfair Display', 'Inter', 'Space Mono', 'Noto Sans Devanagari', 'Noto Serif Devanagari'):
            self.assertIn(f"font-family: '{family}'", css)
        self.assertTrue((static / 'fonts' / 'OFL.txt').exists())


class NotifyUsersCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        folder = Path(self.directory.name)
        self.message = folder / 'notice.txt'
        self.message.write_text('Hi {first_name}, an important notice.')
        self.emails = folder / 'affected.txt'
        self.emails.write_text('Affected@example.com\nunknown@example.com\n')
        make_user('affected@example.com')
        make_user('fine@example.com')
        make_user('gone@example.com', erased_at=timezone.now())

    def _run(self, *args):
        out = StringIO()
        call_command('notify_users', '--subject', 'Notice', '--message-file', str(self.message), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_sends_nothing_and_lists_recipients(self):
        out = self._run('--emails', str(self.emails))
        self.assertIn('1 recipient(s).', out)
        self.assertIn('No active account for unknown@example.com', out)
        self.assertIn('Dry run', out)
        self.assertEqual(mail.outbox, [])

    def test_send_to_listed_accounts(self):
        self._run('--emails', str(self.emails), '--send')
        self.assertEqual([m.to for m in mail.outbox], [['affected@example.com']])
        self.assertEqual(mail.outbox[0].body, 'Hi Ram, an important notice.')

    def test_all_active_skips_deleted_accounts(self):
        self._run('--all-active', '--send')
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['affected@example.com', 'fine@example.com'])
