"""Institutional usage: reads counted per member, the organization dashboard
for its managers, member removal and invitations, the monthly usage email
with its CSV, renewal reminders, and the staff side."""
import datetime

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from articles.models import Article
from sections.models import Section
from users.models import User
from users.privacy import export_user_data

from . import org_reports
from .institutions import organization_for
from .models import Organization, OrganizationMember, OrganizationRead, SubscriptionPlan
from .test_lifecycle import make_plan, make_user


class OrgTestBase(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.plan = make_plan('Institutional', price=50000, days=365, plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL)
        self.org = Organization.objects.create(
            name='Nepal Health Research Council', email_domains='nhrc.gov.np', plan=self.plan, seats=3,
            contact_email='boss@nhrc.gov.np',
            start_date=self.today - datetime.timedelta(days=60), end_date=self.today + datetime.timedelta(days=300),
        )
        self.section = Section.objects.create(name='Org test section', slug='org-test-section')
        self.article = Article.objects.create(
            title='Dengue season', slug='dengue-season', status=Article.Status.PUBLISHED, section=self.section,
            access_type=Article.AccessType.SUBSCRIPTION, html_content='<p>x</p>',
        )
        self.boss = self.member('boss@nhrc.gov.np')
        self.reader = self.member('reader@nhrc.gov.np')

    def member(self, email):
        user = make_user(email, email_confirmed_at=timezone.now())
        self.assertEqual(organization_for(user), self.org)
        return user

    def read(self, user, article=None, day=None):
        return OrganizationRead.objects.create(
            organization=self.org, user=user, article=article or self.article, read_on=day or self.today,
        )


class RecordingReadsTests(OrgTestBase):
    def test_contact_email_becomes_manager_others_do_not(self):
        self.assertTrue(OrganizationMember.objects.get(user=self.boss).is_manager)
        self.assertFalse(OrganizationMember.objects.get(user=self.reader).is_manager)

    def test_reading_counts_once_a_day(self):
        self.client.force_login(self.reader)
        url = reverse('articles:article_detail', args=[self.article.slug])
        self.client.get(url)
        self.client.get(url)
        self.assertEqual(OrganizationRead.objects.filter(user=self.reader).count(), 1)

    def test_staff_and_outsiders_are_not_counted(self):
        outsider = make_user('someone@example.org', email_confirmed_at=timezone.now())
        self.client.force_login(outsider)
        self.client.get(reverse('articles:article_detail', args=[self.article.slug]))
        self.assertFalse(OrganizationRead.objects.exists())

    def test_removed_member_loses_access_and_cannot_rejoin(self):
        OrganizationMember.objects.filter(user=self.reader).update(removed_at=timezone.now())
        self.assertIsNone(organization_for(self.reader))
        self.assertEqual(OrganizationMember.objects.filter(user=self.reader).count(), 1)

    def test_removed_members_free_their_seat(self):
        self.member('third@nhrc.gov.np')
        self.assertIsNone(organization_for(make_user('fourth@nhrc.gov.np', email_confirmed_at=timezone.now())))
        OrganizationMember.objects.filter(user=self.reader).update(removed_at=timezone.now())
        self.assertEqual(organization_for(make_user('fifth@nhrc.gov.np', email_confirmed_at=timezone.now())), self.org)


class SummaryTests(OrgTestBase):
    def test_summary_counts(self):
        self.read(self.reader)
        self.read(self.boss)
        self.read(self.reader, day=self.today - datetime.timedelta(days=40))  # another month
        start, end = org_reports.month_bounds(self.today)
        data = org_reports.summary(self.org, start, end)
        self.assertEqual(data['reads'], 2)
        self.assertEqual(data['active_readers'], 2)
        self.assertEqual(data['member_count'], 2)
        self.assertEqual(data['seats_left'], 1)
        self.assertEqual(data['top_articles'][0]['n'], 2)
        self.assertEqual(data['top_sections'][0]['article__section__name'], 'Org test section')
        by_email = {m.user.email: m for m in data['members']}
        self.assertEqual(by_email['reader@nhrc.gov.np'].period_reads, 1)

    def test_monthly_series_covers_twelve_months(self):
        self.read(self.reader)
        series = org_reports.monthly_series(self.org)
        self.assertEqual(len(series), 12)
        self.assertEqual(series[-1]['reads'], 1)
        self.assertEqual(series[-1]['pct'], 100)

    def test_csv_never_lists_which_articles_a_member_read(self):
        self.read(self.reader)
        start, end = org_reports.month_bounds(self.today)
        csv_text = org_reports.csv_report(self.org, start, end)
        member_rows = [line for line in csv_text.splitlines() if 'reader@nhrc.gov.np' in line]
        self.assertEqual(len(member_rows), 1)
        self.assertNotIn('Dengue', member_rows[0])
        self.assertIn('Dengue season', csv_text)  # organization-wide top list


class DashboardTests(OrgTestBase):
    def test_manager_sees_dashboard(self):
        self.read(self.reader)
        self.client.force_login(self.boss)
        response = self.client.get(reverse('billing:org_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nepal Health Research Council')
        self.assertContains(response, 'reader@nhrc.gov.np')
        self.assertNotContains(response, 'Advertisement —')

    def test_ordinary_members_and_strangers_get_404(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse('billing:org_dashboard')).status_code, 404)
        self.assertEqual(self.client.get(reverse('billing:org_dashboard_for', args=[self.org.pk])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('billing:org_dashboard')).status_code, 302)

    def test_csv_download(self):
        self.client.force_login(self.boss)
        response = self.client.get(reverse('billing:org_report_csv', args=[self.org.pk]), {'month': self.today.strftime('%Y-%m')})
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('reader@nhrc.gov.np', response.content.decode())

    def test_bad_month_falls_back_to_this_month(self):
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(reverse('billing:org_dashboard'), {'month': 'nope'}).status_code, 200)

    def test_remove_and_restore_member(self):
        membership = OrganizationMember.objects.get(user=self.reader)
        self.client.force_login(self.boss)
        self.client.post(reverse('billing:org_member_remove', args=[self.org.pk, membership.pk]))
        membership.refresh_from_db()
        self.assertIsNotNone(membership.removed_at)
        self.assertIsNone(organization_for(self.reader))
        self.assertEqual(mail.outbox[-1].to, ['reader@nhrc.gov.np'])
        self.client.post(reverse('billing:org_member_restore', args=[self.org.pk, membership.pk]))
        membership.refresh_from_db()
        self.assertIsNone(membership.removed_at)

    def test_restore_respects_seats(self):
        membership = OrganizationMember.objects.get(user=self.reader)
        membership.removed_at = timezone.now()
        membership.save()
        self.member('third@nhrc.gov.np')
        self.member('fourth@nhrc.gov.np')
        self.client.force_login(self.boss)
        self.client.post(reverse('billing:org_member_restore', args=[self.org.pk, membership.pk]))
        membership.refresh_from_db()
        self.assertIsNotNone(membership.removed_at)

    def test_manager_toggle_but_not_on_yourself(self):
        reader_m = OrganizationMember.objects.get(user=self.reader)
        boss_m = OrganizationMember.objects.get(user=self.boss)
        self.client.force_login(self.boss)
        self.client.post(reverse('billing:org_member_manager', args=[self.org.pk, reader_m.pk]))
        self.client.post(reverse('billing:org_member_manager', args=[self.org.pk, boss_m.pk]))
        reader_m.refresh_from_db()
        boss_m.refresh_from_db()
        self.assertTrue(reader_m.is_manager)
        self.assertTrue(boss_m.is_manager)

    def test_member_actions_need_a_manager(self):
        boss_m = OrganizationMember.objects.get(user=self.boss)
        self.client.force_login(self.reader)
        response = self.client.post(reverse('billing:org_member_remove', args=[self.org.pk, boss_m.pk]))
        self.assertEqual(response.status_code, 404)

    def test_invite_only_at_the_organization_domains(self):
        self.client.force_login(self.boss)
        mail.outbox.clear()
        self.client.post(reverse('billing:org_invite', args=[self.org.pk]),
                         {'emails': 'new@nhrc.gov.np, someone@gmail.com\nnot-an-email'})
        self.assertEqual([m.to for m in mail.outbox], [['new@nhrc.gov.np']])
        self.assertIn('Nepal Health Research Council', mail.outbox[0].subject)

    def test_billing_and_profile_link_to_dashboard(self):
        self.client.force_login(self.boss)
        url = reverse('billing:org_dashboard_for', args=[self.org.pk])
        self.assertContains(self.client.get(reverse('billing:account')), url)
        self.assertContains(self.client.get(reverse('users:profile')), url)
        self.client.force_login(self.reader)
        self.assertNotContains(self.client.get(reverse('billing:account')), url)


class EmailTests(OrgTestBase):
    def test_monthly_report_with_csv(self):
        manager = make_user('am@ajna.example', role=User.Role.EDITOR)
        self.org.account_manager = manager
        self.org.save()
        self.read(self.reader, day=org_reports.previous_month()[0])
        mail.outbox.clear()
        self.assertEqual(org_reports.send_monthly_reports(), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['boss@nhrc.gov.np'])
        self.assertEqual(message.cc, ['am@ajna.example'])
        name, content, mimetype = message.attachments[0]
        self.assertEqual(mimetype, 'text/csv')
        self.assertIn('reader@nhrc.gov.np', content)

    def test_no_report_for_deals_outside_last_month(self):
        start, _end = org_reports.previous_month()
        self.org.start_date = self.today
        self.org.save()
        mail.outbox.clear()
        self.assertEqual(org_reports.send_monthly_reports(), 0)

    def test_renewal_reminders_once_per_stage(self):
        make_user('eic@ajna.example', role=User.Role.EDITOR_IN_CHIEF)
        self.org.end_date = self.today + datetime.timedelta(days=25)
        self.org.save()
        mail.outbox.clear()
        self.assertEqual(org_reports.send_renewal_reminders(), 1)
        self.assertIn('25 days', mail.outbox[0].subject)
        self.assertIn('eic@ajna.example', mail.outbox[0].to)
        self.assertEqual(org_reports.send_renewal_reminders(), 0)  # same stage, not again
        self.org.end_date = self.today + datetime.timedelta(days=5)
        self.org.save()
        self.assertEqual(org_reports.send_renewal_reminders(), 1)  # new end date / stage

    def test_renewal_far_away_sends_nothing(self):
        self.assertEqual(org_reports.send_renewal_reminders(), 0)

    def test_ended_reminder(self):
        self.org.end_date = self.today - datetime.timedelta(days=1)
        self.org.save()
        self.assertEqual(org_reports.send_renewal_reminders(), 1)
        self.assertIn('has ended', mail.outbox[-1].subject)


class StaffSideTests(OrgTestBase):
    def setUp(self):
        super().setUp()
        self.eic = make_user('eic@ajna.example', role=User.Role.EDITOR_IN_CHIEF)
        self.client.force_login(self.eic)

    def test_edit_page_shows_usage_and_members(self):
        self.read(self.reader)
        response = self.client.get(reverse('billing:manage_organization_update', args=[self.org.pk]))
        self.assertContains(response, 'Usage this month')
        self.assertContains(response, 'MANAGER')
        self.assertIn(self.eic, response.context['form'].fields['account_manager'].queryset)

    def test_send_report_now(self):
        mail.outbox.clear()
        self.client.post(reverse('billing:manage_organization_send_report', args=[self.org.pk]))
        self.assertEqual(len(mail.outbox), 1)

    def test_staff_manager_toggle(self):
        membership = OrganizationMember.objects.get(user=self.reader)
        self.client.post(reverse('billing:manage_organization_member_manager', args=[self.org.pk, membership.pk]))
        membership.refresh_from_db()
        self.assertTrue(membership.is_manager)

    def test_readers_cannot_use_staff_actions(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('billing:manage_organization_send_report', args=[self.org.pk]))
        self.assertIn(response.status_code, (302, 403))


class PrivacyTests(OrgTestBase):
    def test_export_includes_reads_through_the_organization(self):
        self.read(self.reader)
        org = export_user_data(self.reader)['organizations'][0]
        self.assertEqual(org['articles_read_through_it'][0]['article'], 'Dengue season')

    def test_erasure_keeps_counts_without_the_name(self):
        from users.privacy import erase_user

        self.read(self.reader)
        erase_user(self.reader)
        read = OrganizationRead.objects.get()
        self.assertIsNone(read.user_id)
        start, end = org_reports.month_bounds(self.today)
        self.assertEqual(org_reports.summary(self.org, start, end)['reads'], 1)
