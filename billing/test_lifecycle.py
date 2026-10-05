"""The billing cycle around a payment: VAT, receipts, the reader's billing
page, early renewal, coming back to the article, expiry reminders, staff
recording money, and institutional access by email domain."""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from articles.models import Article
from users.models import User

from . import payments
from .access import article_is_accessible, user_has_active_subscription, user_has_perk
from .forms import OrganizationForm
from .institutions import organization_for
from .models import ArticlePurchase, Organization, OrganizationMember, Payment, SubscriptionPlan, UserSubscription
from .money import split_vat_inclusive, vat_breakdown
from .reminders import send_subscription_reminders
from .tests import FONEPAY_TEST_SETTINGS

STUB = override_settings(PAYMENT_GATEWAY='stub')


def make_user(email, **extra):
    return User.objects.create_user(email=email, password='pw', first_name='Rita', last_name='Shah', **extra)


def make_plan(name='Monthly', price=499, days=30, **extra):
    return SubscriptionPlan.objects.create(
        name=name, plan_type=extra.pop('plan_type', SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY),
        price=price, duration_days=days, **extra,
    )


def subscribe(user, plan, start, end, **extra):
    return UserSubscription.objects.create(user=user, plan=plan, start_date=start, end_date=end, **extra)


class VatTests(TestCase):
    def test_vat_is_added_on_top_and_rounded_to_the_paisa(self):
        self.assertEqual(vat_breakdown(499), (Decimal('499.00'), Decimal('64.87'), Decimal('563.87')))
        self.assertEqual(vat_breakdown(Decimal('0.50')), (Decimal('0.50'), Decimal('0.07'), Decimal('0.57')))

    def test_an_amount_received_including_vat_is_split(self):
        self.assertEqual(split_vat_inclusive('563.87'), (Decimal('499.00'), Decimal('64.87'), Decimal('563.87')))
        subtotal, vat, total = split_vat_inclusive(1000)
        self.assertEqual(subtotal + vat, total)

    @override_settings(VAT_RATE=Decimal('0'))
    def test_rate_comes_from_settings(self):
        self.assertEqual(vat_breakdown(100)[2], Decimal('100.00'))

    def test_prices_say_plus_vat(self):
        plan = make_plan(price=499)
        page = self.client.get(reverse('billing:plan_detail', args=[plan.pk]))
        self.assertContains(page, '+ 13% VAT')
        self.assertContains(page, 'Rs. 563.87')


@STUB
class ReceiptTests(TestCase):
    def setUp(self):
        self.reader = make_user('receipt@example.com')
        self.plan = make_plan()

    def _buy(self, user=None):
        self.client.force_login(user or self.reader)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('billing:subscribe_checkout', args=[self.plan.pk]))
        return Payment.objects.filter(user=user or self.reader).latest('created_at')

    def test_receipt_numbers_are_sequential(self):
        first = self._buy()
        second = self._buy(make_user('second@example.com'))
        number = int(first.receipt_number.removeprefix('AHL-'))
        self.assertEqual(second.receipt_number, f'AHL-{number + 1:06d}')

    @override_settings(BUSINESS_PAN='600123456', BUSINESS_ADDRESS='Lalitpur, Nepal')
    def test_receipt_email_has_the_vat_breakdown(self):
        payment = self._buy()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['receipt@example.com'])
        self.assertIn(payment.receipt_number, message.subject)
        for text in ('Rs. 499', 'VAT (13%): Rs. 64.87', 'Total paid: Rs. 563.87', 'PAN 600123456'):
            self.assertIn(text, message.body)
        self.assertIn(reverse('billing:receipt', args=[payment.reference]), message.body)

    @override_settings(BUSINESS_PAN='600123456')
    def test_receipt_page_for_the_payer_and_senior_staff_only(self):
        payment = self._buy()
        url = reverse('billing:receipt', args=[payment.reference])
        page = self.client.get(url)
        self.assertContains(page, payment.receipt_number)
        self.assertContains(page, 'PAN / VAT no. 600123456')
        self.assertContains(page, 'Rs. 64.87')
        self.client.force_login(make_user('nosy@example.com'))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(make_user('editor-receipt@example.com', role=User.Role.EDITOR))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(make_user('eic-receipt@example.com', role=User.Role.EDITOR_IN_CHIEF))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_unpaid_payment_has_no_receipt(self):
        pending = Payment.objects.create(
            user=self.reader, kind=Payment.Kind.SUBSCRIPTION, plan=self.plan, amount=1, description='x',
            expires_at=timezone.now() + datetime.timedelta(minutes=5),
        )
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse('billing:receipt', args=[pending.reference])).status_code, 404)


@override_settings(**FONEPAY_TEST_SETTINGS)
class FonepayEmailTests(TestCase):
    def setUp(self):
        self.reader = make_user('fonepay-mail@example.com')
        self.plan = make_plan()
        self.payment = Payment.objects.create(
            user=self.reader, kind=Payment.Kind.SUBSCRIPTION, plan=self.plan, subtotal=499, vat_amount=Decimal('64.87'),
            amount=Decimal('563.87'), description='Subscription — Monthly',
            expires_at=timezone.now() + datetime.timedelta(minutes=10),
        )

    def _verify(self, **status):
        with patch('billing.fonepay.payment_status', return_value=status), self.captureOnCommitCallbacks(execute=True):
            return payments.verify_payment(self.payment)

    def test_success_sends_a_receipt(self):
        self.assertEqual(self._verify(paymentStatus='success', totalTransactionAmount='563.87').status, Payment.Status.SUCCESS)
        self.assertIn('Receipt AHL-', mail.outbox[0].subject)

    def test_price_without_vat_is_underpaid(self):
        self.assertEqual(self._verify(paymentStatus='success', totalTransactionAmount='499').status, Payment.Status.FAILED)
        self.assertFalse(UserSubscription.objects.exists())
        self.assertIn('less than', mail.outbox[0].body)
        self.assertIn(self.payment.reference, mail.outbox[0].body)

    def test_declined_payment_emails_a_retry_link(self):
        self._verify(paymentStatus='failed')
        self.assertIn('didn’t go through', mail.outbox[0].subject)
        self.assertIn(reverse('billing:subscribe_checkout', args=[self.plan.pk]), mail.outbox[0].body)

    def test_abandoned_payment_sends_nothing(self):
        Payment.objects.filter(pk=self.payment.pk).update(expires_at=timezone.now() - datetime.timedelta(minutes=30))
        self.payment.refresh_from_db()
        self.assertEqual(self._verify(paymentStatus='pending').status, Payment.Status.EXPIRED)
        self.assertEqual(mail.outbox, [])

    def test_fonepay_is_asked_for_the_total_with_vat(self):
        reader = make_user('fonepay-total@example.com')
        with patch('billing.fonepay.generate_intent_qr', return_value={'qrMessage': 'QR'}) as generate:
            payment = payments.start_payment(reader, kind=Payment.Kind.SUBSCRIPTION, price=self.plan.price,
                                             description='x', plan=self.plan)
        self.assertEqual(generate.call_args.args[0], Decimal('563.87'))
        self.assertEqual((payment.subtotal, payment.vat_amount), (Decimal('499.00'), Decimal('64.87')))


@STUB
class RenewalAndAccountPageTests(TestCase):
    def setUp(self):
        self.reader = make_user('renew@example.com')
        self.monthly = make_plan()
        self.annual = make_plan('Annual', price=4999, days=365, plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_ANNUAL)
        self.today = timezone.localdate()
        self.client.force_login(self.reader)

    def test_switching_to_annual_early_queues_it_after_the_current_month(self):
        subscribe(self.reader, self.monthly, self.today - datetime.timedelta(days=20), self.today + datetime.timedelta(days=10))
        self.client.post(reverse('billing:subscribe_checkout', args=[self.annual.pk]))
        annual = UserSubscription.objects.get(plan=self.annual)
        self.assertEqual(annual.start_date, self.today + datetime.timedelta(days=11))
        # Still on the monthly plan today; nothing lost.
        self.assertEqual(UserSubscription.objects.get(plan=self.monthly).end_date, self.today + datetime.timedelta(days=10))

    def test_lapsed_subscription_renews_from_today(self):
        subscribe(self.reader, self.monthly, self.today - datetime.timedelta(days=40), self.today - datetime.timedelta(days=10))
        self.client.post(reverse('billing:subscribe_checkout', args=[self.monthly.pk]))
        self.assertEqual(UserSubscription.objects.latest('created_at').start_date, self.today)

    def test_account_page_shows_current_next_payments_and_purchases(self):
        subscribe(self.reader, self.monthly, self.today, self.today + datetime.timedelta(days=5))
        self.client.post(reverse('billing:subscribe_checkout', args=[self.monthly.pk]))
        article = Article.objects.create(title='Bought story', slug='bought-story', status=Article.Status.PUBLISHED)
        ArticlePurchase.objects.create(user=self.reader, article=article, amount=100)
        response = self.client.get(reverse('billing:account'))
        self.assertEqual(response.context['current'].end_date, self.today + datetime.timedelta(days=5))
        self.assertEqual(len(response.context['upcoming']), 1)
        self.assertEqual(response.context['paid_through'], self.today + datetime.timedelta(days=36))
        self.assertEqual(response.context['days_left'], 36)
        payment = Payment.objects.get(user=self.reader)
        self.assertContains(response, payment.receipt_number)
        self.assertContains(response, 'Bought story')
        self.assertContains(response, reverse('billing:subscribe_checkout', args=[self.monthly.pk]))

    def test_account_page_with_nothing(self):
        response = self.client.get(reverse('billing:account'))
        self.assertContains(response, 'No active subscription.')
        self.assertContains(response, 'No payments yet.')

    def test_profile_links_to_billing(self):
        subscribe(self.reader, self.monthly, self.today, self.today + datetime.timedelta(days=5))
        response = self.client.get(reverse('users:profile'))
        self.assertContains(response, 'Monthly · until')
        self.assertContains(response, reverse('billing:account'))

    def test_others_see_nothing_of_mine(self):
        subscribe(self.reader, self.monthly, self.today, self.today + datetime.timedelta(days=5))
        self.client.force_login(make_user('other-account@example.com'))
        self.assertIsNone(self.client.get(reverse('billing:account')).context['current'])


@STUB
class ReturnToArticleTests(TestCase):
    def setUp(self):
        self.reader = make_user('return@example.com')
        self.plan = make_plan()
        self.article = Article.objects.create(
            title='Locked story', slug='locked-story', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.SUBSCRIPTION, html_content='<p>x</p>',
        )
        self.client.force_login(self.reader)

    @patch('billing.access.FREE_SAMPLE_LIMIT_PER_MONTH', 0)  # no free read: the paywall shows
    def test_paywall_carries_the_article_to_checkout_and_back(self):
        article_url = reverse('articles:article_detail', args=[self.article.slug])
        paywall = self.client.get(article_url)
        self.assertContains(paywall, f'{reverse("billing:plan_browse")}?next=/articles/locked-story/')
        plans = self.client.get(reverse('billing:plan_browse'), {'next': article_url})
        self.assertContains(plans, f'{reverse("billing:subscribe_checkout", args=[self.plan.pk])}?next=/articles/locked-story/')
        response = self.client.post(reverse('billing:subscribe_checkout', args=[self.plan.pk]), {'next': article_url})
        self.assertRedirects(response, article_url, fetch_redirect_response=False)

    def test_other_sites_are_never_a_destination(self):
        for bad in ('https://evil.example/', '//evil.example/', '/\\evil.example'):
            response = self.client.post(reverse('billing:subscribe_checkout', args=[self.plan.pk]), {'next': bad})
            self.assertRedirects(response, reverse('billing:account'), fetch_redirect_response=False, msg_prefix=bad)

    @override_settings(**FONEPAY_TEST_SETTINGS)
    def test_fonepay_payment_remembers_where_to_return(self):
        with patch('billing.fonepay.generate_intent_qr', return_value={'qrMessage': 'QR'}):
            self.client.post(reverse('billing:subscribe_checkout', args=[self.plan.pk]), {'next': '/articles/locked-story/'})
        payment = Payment.objects.get()
        self.assertEqual(payments.success_url(payment), '/articles/locked-story/')


class ReminderTests(TestCase):
    def setUp(self):
        self.reader = make_user('remind@example.com')
        self.plan = make_plan()
        self.today = timezone.localdate()

    def _ending_in(self, days, user=None):
        return subscribe(user or self.reader, self.plan, self.today - datetime.timedelta(days=20), self.today + datetime.timedelta(days=days))

    def test_week_before_and_day_before_each_once(self):
        subscription = self._ending_in(7)
        self.assertEqual(send_subscription_reminders(), 1)
        self.assertEqual(send_subscription_reminders(), 0)
        self.assertIn('ends in 7 days', mail.outbox[0].subject)
        self.assertIn(reverse('billing:subscribe_checkout', args=[self.plan.pk]), mail.outbox[0].body)
        UserSubscription.objects.filter(pk=subscription.pk).update(end_date=self.today + datetime.timedelta(days=1))
        self.assertEqual(send_subscription_reminders(), 1)
        self.assertIn('ends tomorrow', mail.outbox[1].subject)

    def test_a_missed_week_sends_only_the_most_urgent(self):
        self._ending_in(1)
        send_subscription_reminders()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('ends tomorrow', mail.outbox[0].subject)
        self.assertEqual(sorted(UserSubscription.objects.get().reminders_sent), ['1', '7'])

    def test_ended_notice_once(self):
        subscribe(self.reader, self.plan, self.today - datetime.timedelta(days=31), self.today - datetime.timedelta(days=1),
                  reminders_sent=['1', '7'])
        self.assertEqual(send_subscription_reminders(), 1)
        self.assertIn('has ended', mail.outbox[0].subject)
        self.assertEqual(send_subscription_reminders(), 0)

    def test_long_ended_subscriptions_are_left_alone(self):
        subscribe(self.reader, self.plan, self.today - datetime.timedelta(days=60), self.today - datetime.timedelta(days=20))
        self.assertEqual(send_subscription_reminders(), 0)

    def test_no_reminder_after_renewing(self):
        current = self._ending_in(7)
        subscribe(self.reader, self.plan, current.end_date + datetime.timedelta(days=1), current.end_date + datetime.timedelta(days=31))
        self.assertEqual(send_subscription_reminders(), 0)

    def test_no_reminder_for_cancelled_or_deactivated(self):
        self._ending_in(7).__class__.objects.update(status=UserSubscription.Status.CANCELLED)
        gone = make_user('gone@example.com', is_active=False)
        self._ending_in(7, user=gone)
        self.assertEqual(send_subscription_reminders(), 0)

    def test_discontinued_plan_points_to_all_plans(self):
        self.plan.is_active = False
        self.plan.save()
        self._ending_in(7)
        send_subscription_reminders()
        self.assertIn(reverse('billing:plan_browse'), mail.outbox[0].body)

    def test_runs_daily_on_the_worker(self):
        from django_q.models import Schedule

        schedule = Schedule.objects.get(name='subscription_reminders_daily')
        self.assertEqual((schedule.func, schedule.schedule_type), ('billing.reminders.send_subscription_reminders', 'D'))


class StaffRecordedPaymentTests(TestCase):
    def setUp(self):
        self.eic = make_user('eic-money@example.com', role=User.Role.EDITOR_IN_CHIEF)
        self.reader = make_user('transfer@example.com')
        self.plan = make_plan()
        self.client.force_login(self.eic)

    def test_bank_transfer_subscription_is_a_payment_with_receipt(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('billing:manage_subscription_grant'), {
                'user': self.reader.pk, 'plan': self.plan.pk, 'amount_received': '563.87',
            })
        subscription = UserSubscription.objects.get(user=self.reader)
        payment = Payment.objects.get(reference=subscription.payment_reference)
        self.assertEqual((payment.gateway, payment.subtotal, payment.vat_amount), (
            Payment.Gateway.MANUAL, Decimal('499.00'), Decimal('64.87'),
        ))
        self.assertEqual(payment.recorded_by, self.eic)
        self.assertEqual(UserSubscription.objects.filter(user=self.reader).count(), 1)  # granted once
        self.assertEqual(mail.outbox[0].to, ['transfer@example.com'])

    def test_complimentary_grant_has_no_payment(self):
        self.client.post(reverse('billing:manage_subscription_grant'), {'user': self.reader.pk, 'plan': self.plan.pk, 'amount_received': '0'})
        self.assertTrue(UserSubscription.objects.filter(user=self.reader).exists())
        self.assertFalse(Payment.objects.exists())

    def test_purchase_grant_records_price_and_refuses_duplicates(self):
        article = Article.objects.create(
            title='Special', slug='special-transfer', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.PAY_PER_ARTICLE, price=150,
        )
        data = {'user': self.reader.pk, 'article': article.pk, 'amount': '169.50'}
        self.client.post(reverse('billing:manage_purchase_grant'), data)
        purchase = ArticlePurchase.objects.get(user=self.reader)
        self.assertEqual(purchase.amount, Decimal('150.00'))
        self.assertEqual(Payment.objects.get().amount, Decimal('169.50'))
        response = self.client.post(reverse('billing:manage_purchase_grant'), data)
        self.assertContains(response, 'already has this article')
        self.assertEqual(Payment.objects.count(), 1)

    def test_payment_list_filters_and_is_senior_only(self):
        Payment.objects.create(user=self.reader, kind=Payment.Kind.SUBSCRIPTION, plan=self.plan, amount=1,
                               description='Failed one', status=Payment.Status.FAILED, expires_at=timezone.now())
        Payment.objects.create(user=self.reader, kind=Payment.Kind.SUBSCRIPTION, plan=self.plan, amount=1,
                               description='Pending one', expires_at=timezone.now())
        url = reverse('billing:manage_payment_list')
        failed = self.client.get(url, {'status': 'failed'}).context['payments']
        self.assertEqual([p.description for p in failed], ['Failed one'])
        self.assertEqual(len(self.client.get(url, {'q': 'transfer@'}).context['payments']), 2)
        self.client.force_login(make_user('editor-payments@example.com', role=User.Role.EDITOR))
        self.assertEqual(self.client.get(url).status_code, 403)


class OrganizationAccessTests(TestCase):
    def setUp(self):
        self.plan = make_plan('Institutional', price=50000, days=365, plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL,
                              grants_full_archive=True)
        self.today = timezone.localdate()
        self.org = Organization.objects.create(
            name='Nepal Health Research Council', email_domains='nhrc.gov.np', plan=self.plan,
            start_date=self.today - datetime.timedelta(days=1), end_date=self.today + datetime.timedelta(days=300),
        )
        self.article = Article.objects.create(
            title='Members only', slug='members-only', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.SUBSCRIPTION, html_content='<p>x</p>',
        )

    def _member(self, email='staff@nhrc.gov.np', confirmed=True):
        return make_user(email, email_confirmed_at=timezone.now() if confirmed else None)

    def test_confirmed_address_at_the_domain_gets_the_plan(self):
        staff = self._member()
        self.assertTrue(user_has_active_subscription(staff))
        self.assertTrue(article_is_accessible(staff, self.article))
        self.assertTrue(user_has_perk(staff, 'grants_full_archive'))
        self.assertTrue(OrganizationMember.objects.filter(organization=self.org, user=staff).exists())

    def test_subdomains_count_and_lookalikes_do_not(self):
        self.assertTrue(user_has_active_subscription(self._member('a@dept.nhrc.gov.np')))
        self.assertFalse(user_has_active_subscription(self._member('a@evilnhrc.gov.np')))
        self.assertFalse(user_has_active_subscription(self._member('a@nhrc.gov.np.evil.example')))

    def test_typing_the_address_is_not_enough(self):
        self.assertFalse(user_has_active_subscription(self._member(confirmed=False)))

    def test_seats_run_out(self):
        self.org.seats = 1
        self.org.save()
        self.assertTrue(user_has_active_subscription(self._member('one@nhrc.gov.np')))
        self.assertFalse(user_has_active_subscription(self._member('two@nhrc.gov.np')))

    def test_ended_or_switched_off_deal_stops_access(self):
        staff = self._member()
        Organization.objects.filter(pk=self.org.pk).update(end_date=self.today - datetime.timedelta(days=1))
        self.assertFalse(user_has_active_subscription(staff))
        Organization.objects.filter(pk=self.org.pk).update(end_date=self.today + datetime.timedelta(days=5), is_active=False)
        self.assertFalse(user_has_active_subscription(staff))

    def test_changing_email_clears_confirmation(self):
        staff = self._member()
        staff.email = 'someone@gmail.com'
        staff.save()
        staff.refresh_from_db()
        self.assertIsNone(staff.email_confirmed_at)

    def test_public_providers_and_bad_domains_are_refused(self):
        for domains, message in (('gmail.com', 'public email provider'), ('not a domain', "isn't a domain"), ('', 'required')):
            form = OrganizationForm(data={
                'name': 'X', 'email_domains': domains, 'plan': self.plan.pk, 'start_date': self.today,
                'end_date': self.today + datetime.timedelta(days=30), 'is_active': 'on',
            })
            self.assertFalse(form.is_valid())
            self.assertIn(message, ' '.join(form.errors['email_domains']))

    def test_institutional_plan_has_no_self_serve_checkout(self):
        self.client.force_login(make_user('buyer-inst@example.com'))
        response = self.client.post(reverse('billing:subscribe_checkout', args=[self.plan.pk]))
        self.assertRedirects(response, reverse('billing:plan_detail', args=[self.plan.pk]), fetch_redirect_response=False)
        self.assertFalse(Payment.objects.exists())
        self.assertContains(self.client.get(reverse('billing:plan_detail', args=[self.plan.pk])), 'ASK ABOUT YOUR ORGANIZATION')


class EmailConfirmationTests(TestCase):
    def setUp(self):
        self.plan = make_plan('Institutional', price=50000, days=365, plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL)
        self.org = Organization.objects.create(
            name='Patan Academy', email_domains='pahs.edu.np', plan=self.plan,
            end_date=timezone.localdate() + datetime.timedelta(days=100),
        )

    def _link(self):
        body = mail.outbox[-1].body
        return body[body.index('/account/confirm-email/'):].split()[0]

    def test_signup_at_an_organization_sends_the_link_and_clicking_it_gives_access(self):
        self.client.post(reverse('users:register'), {
            'first_name': 'Asha', 'last_name': 'Rai', 'email': 'asha@pahs.edu.np',
            'password1': 'Kathmandu-2026!', 'password2': 'Kathmandu-2026!',
        })
        user = User.objects.get(email='asha@pahs.edu.np')
        self.assertFalse(user_has_active_subscription(user))
        self.assertIn('Patan Academy', mail.outbox[-1].body)
        response = self.client.get(self._link())
        self.assertRedirects(response, reverse('billing:account'), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertIsNotNone(user.email_confirmed_at)
        self.assertEqual(organization_for(user), self.org)

    @patch('billing.access.FREE_SAMPLE_LIMIT_PER_MONTH', 0)  # no free read: the paywall shows
    def test_paywall_and_billing_page_offer_the_link(self):
        user = make_user('late@pahs.edu.np')
        article = Article.objects.create(title='Locked', slug='locked-for-org', status=Article.Status.PUBLISHED,
                                         access_type=Article.AccessType.SUBSCRIPTION, html_content='<p>x</p>')
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse('articles:article_detail', args=[article.slug])), 'EMAIL ME A CONFIRMATION LINK')
        self.assertContains(self.client.get(reverse('billing:account')), 'Patan Academy')
        self.client.post(reverse('users:send_email_confirmation'), {'next': '/articles/locked-for-org/'})
        self.client.get(self._link())
        self.assertTrue(article_is_accessible(User.objects.get(pk=user.pk), article))

    def test_link_dies_when_the_email_changes(self):
        user = make_user('mover@pahs.edu.np')
        self.client.force_login(user)
        self.client.post(reverse('users:send_email_confirmation'))
        link = self._link()
        user.email = 'mover@other.example'
        user.save()
        self.assertEqual(self.client.get(link).status_code, 400)
        user.refresh_from_db()
        self.assertIsNone(user.email_confirmed_at)

    def test_tampered_or_expired_link_is_refused(self):
        user = make_user('tamper@pahs.edu.np')
        self.client.force_login(user)
        self.client.post(reverse('users:send_email_confirmation'))
        link = self._link()
        self.assertEqual(self.client.get(link[:-3] + 'abc/').status_code, 400)
        # Links last LINK_VALID_DAYS; at 0 days any link is already too old.
        with patch('users.email_confirmation.LINK_VALID_DAYS', 0):
            self.assertEqual(self.client.get(link).status_code, 400)
        self.assertEqual(self.client.get(link).status_code, 302)

    def test_password_reset_also_confirms_the_address(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        user = make_user('reset@pahs.edu.np')
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        url = reverse('users:password_reset_confirm', args=[uid, default_token_generator.make_token(user)])
        form_url = self.client.get(url).url
        self.client.post(form_url, {'new_password1': 'Kathmandu-2026!', 'new_password2': 'Kathmandu-2026!'})
        user.refresh_from_db()
        self.assertIsNotNone(user.email_confirmed_at)


class OrganizationStaffScreenTests(TestCase):
    def setUp(self):
        self.eic = make_user('eic-org@example.com', role=User.Role.EDITOR_IN_CHIEF)
        self.plan = make_plan('Institutional', price=50000, days=365, plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL)
        self.client.force_login(self.eic)

    def _data(self, **extra):
        data = {
            'name': 'BP Koirala Institute', 'email_domains': '@BPKIHS.edu\nbpkihs.edu', 'plan': self.plan.pk,
            'start_date': timezone.localdate(), 'end_date': timezone.localdate() + datetime.timedelta(days=365),
            'is_active': 'on', 'contact_email': 'library@bpkihs.edu',
        }
        data.update(extra)
        return data

    def test_create_with_a_payment_sends_the_receipt_to_the_contact(self):
        self.assertEqual(self.client.get(reverse('billing:manage_organization_create')).context['form'].initial['plan'], self.plan)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('billing:manage_organization_create'), self._data(amount_received='56500'))
        self.assertRedirects(response, reverse('billing:manage_organization_list'), fetch_redirect_response=False)
        org = Organization.objects.get()
        self.assertEqual(org.domains, ['bpkihs.edu'])
        payment = Payment.objects.get()
        self.assertEqual((payment.organization, payment.kind, payment.subtotal), (org, Payment.Kind.INSTITUTIONAL, Decimal('50000.00')))
        self.assertEqual(mail.outbox[0].to, ['library@bpkihs.edu'])
        self.assertContains(self.client.get(reverse('billing:manage_organization_update', args=[org.pk])), payment.receipt_number)

    def test_a_payment_needs_a_contact_email(self):
        response = self.client.post(reverse('billing:manage_organization_create'), self._data(amount_received='100', contact_email=''))
        self.assertIn('contact_email', response.context['form'].errors)
        self.assertFalse(Organization.objects.exists())

    def test_end_before_start_is_refused(self):
        response = self.client.post(reverse('billing:manage_organization_create'), self._data(
            end_date=timezone.localdate() - datetime.timedelta(days=1),
        ))
        self.assertIn('end_date', response.context['form'].errors)

    def test_institutional_revenue_counts_as_subscriptions(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('billing:manage_organization_create'), self._data(amount_received='56500'))
        self.assertEqual(self.client.get(reverse('admin_custom:revenue')).context['subscription_total'], Decimal('50000.00'))

    def test_editors_cannot_manage_organizations(self):
        self.client.force_login(make_user('editor-org@example.com', role=User.Role.EDITOR))
        self.assertEqual(self.client.get(reverse('billing:manage_organization_list')).status_code, 403)
        self.assertEqual(self.client.post(reverse('billing:manage_organization_create'), self._data()).status_code, 403)


class ReceiptDeployCheckTests(TestCase):
    def test_live_payments_without_pan_warn(self):
        from articles.checks import check_receipt_details

        with self.settings(DEBUG=False, PAYMENT_GATEWAY='fonepay', BUSINESS_PAN='', BUSINESS_ADDRESS='Lalitpur'):
            self.assertEqual([w.id for w in check_receipt_details(None)], ['ajna.W001'])
        with self.settings(DEBUG=False, PAYMENT_GATEWAY='fonepay', BUSINESS_PAN='600123456', BUSINESS_ADDRESS='Lalitpur'):
            self.assertEqual(check_receipt_details(None), [])
