"""Promo codes and free trials (billing/promotions.py): price maths, every
condition, checkout with a code (stub and Fonepay), 100%-off grants, trial
codes at /redeem/, receipts, staff management and the data export."""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from articles.models import Article
from training.models import Enrollment, TrainingCourse
from users.models import User
from users.privacy import export_user_data

from . import promotions
from .forms import PromoCodeForm
from .models import ArticlePurchase, Payment, PromoCode, PromoRedemption, SubscriptionPlan, UserSubscription
from .test_lifecycle import make_plan, make_user
from .tests import FONEPAY_TEST_SETTINGS

STUB = override_settings(PAYMENT_GATEWAY='stub')


def make_code(code='LAUNCH50', **extra):
    data = {'percent_off': 50, 'applies_to_subscriptions': True}
    data.update(extra)
    return PromoCode.objects.create(code=code, **data)


class QuoteTests(TestCase):
    def test_percent_and_vat_on_the_discounted_price(self):
        quote = promotions.quote(Decimal('499'), make_code())
        self.assertEqual(quote['discount'], Decimal('249.50'))
        self.assertEqual(quote['price'], Decimal('249.50'))
        self.assertEqual(quote['vat'], Decimal('32.44'))
        self.assertEqual(quote['total'], Decimal('281.94'))
        self.assertFalse(quote['is_free'])

    def test_amount_off_never_exceeds_the_price(self):
        code = make_code('FLAT', percent_off=None, amount_off=Decimal('1000'))
        quote = promotions.quote(Decimal('499'), code)
        self.assertEqual(quote['discount'], Decimal('499.00'))
        self.assertTrue(quote['is_free'])
        self.assertEqual(quote['total'], Decimal('0.00'))

    def test_no_code(self):
        quote = promotions.quote(Decimal('499'))
        self.assertEqual((quote['discount'], quote['total']), (Decimal('0.00'), Decimal('563.87')))

    def test_code_is_stored_in_capitals(self):
        self.assertEqual(make_code('student30').code, 'STUDENT30')
        self.assertEqual(promotions.find(' student30 ').code, 'STUDENT30')


class ConditionTests(TestCase):
    def setUp(self):
        self.user = make_user('reader@example.com')
        self.plan = make_plan()

    def check(self, code, kind='subscription', **item):
        promotions.validate(code, self.user, kind=kind, **({'plan': self.plan} if kind == 'subscription' else {}), **item)

    def assertRefused(self, code, text, **kwargs):
        with self.assertRaisesMessage(promotions.PromoError, text):
            self.check(code, **kwargs)

    def test_active_dates_and_limits(self):
        today = timezone.localdate()
        self.assertRefused(make_code('OFF', is_active=False), 'no longer active')
        self.assertRefused(make_code('SOON', valid_from=today + datetime.timedelta(days=2)), 'can be used from')
        self.assertRefused(make_code('OLD', valid_until=today - datetime.timedelta(days=1)), 'expired')
        full = make_code('FULL', max_redemptions=1)
        PromoRedemption.objects.create(code=full, user=make_user('other@example.com'), item='x')
        self.assertRefused(full, 'fully used')
        once = make_code('ONCE')
        PromoRedemption.objects.create(code=once, user=self.user, item='x')
        self.assertRefused(once, 'already used')

    def test_student_domains_need_a_confirmed_address(self):
        code = make_code('STUDENT30', kind=PromoCode.Kind.STUDENT, email_domains='edu.np')
        self.assertRefused(code, 'only for email addresses at edu.np')
        student = make_user('ram@ku.edu.np')
        with self.assertRaisesMessage(promotions.PromoError, 'Confirm your email'):
            promotions.validate(code, student, kind='subscription', plan=self.plan)
        student.email_confirmed_at = timezone.now()
        student.save()
        promotions.validate(code, student, kind='subscription', plan=self.plan)

    def test_new_subscribers_only(self):
        code = make_code('NEW', new_subscribers_only=True)
        self.check(code)
        today = timezone.localdate()
        UserSubscription.objects.create(user=self.user, plan=self.plan, start_date=today, end_date=today)
        self.assertRefused(code, 'new subscribers only')

    def test_what_it_applies_to(self):
        self.assertRefused(make_code('SUBS'), 'special articles', kind='article')
        self.assertRefused(make_code('NOSUB', applies_to_subscriptions=False, applies_to_articles=True), 'subscriptions')
        other = make_plan('Annual', price=4999, days=365, plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_ANNUAL)
        only_annual = make_code('ANNUAL')
        only_annual.plans.set([other])
        self.assertRefused(only_annual, 'this plan')
        course = TrainingCourse.objects.create(title='Course', description='d', price=1000, duration='1 week', instructor='I')
        other_course = TrainingCourse.objects.create(title='Other', description='d', price=1000, duration='1 week', instructor='I')
        course_code = make_code('COURSE', applies_to_subscriptions=False, applies_to_courses=True)
        course_code.courses.set([other_course])
        self.assertRefused(course_code, 'this course', kind='course', course=course)

    def test_trial_codes_are_not_used_at_checkout(self):
        trial = make_code('TRY7', percent_off=None, trial_days=7, trial_plan=self.plan)
        self.assertRefused(trial, 'free-trial code')


@STUB
class CheckoutTests(TestCase):
    def setUp(self):
        self.user = make_user('reader@example.com')
        self.plan = make_plan(price=499)
        self.code = make_code(description='Launch offer — 50% off')
        self.client.force_login(self.user)
        self.url = reverse('billing:subscribe_checkout', args=[self.plan.pk])

    def test_apply_then_pay(self):
        response = self.client.post(self.url, {'promo_code': 'launch50', 'apply_code': '1'})
        self.assertContains(response, 'Discount (LAUNCH50)')
        self.assertContains(response, 'Rs. 281.94')
        self.assertFalse(Payment.objects.exists())

        self.client.post(self.url, {})
        payment = Payment.objects.get()
        self.assertEqual(payment.promo_code, self.code)
        self.assertEqual((payment.list_price, payment.discount_amount, payment.subtotal, payment.amount),
                         (Decimal('499.00'), Decimal('249.50'), Decimal('249.50'), Decimal('281.94')))
        self.assertEqual(PromoRedemption.objects.get().payment, payment)
        self.assertNotIn(promotions.SESSION_KEY, self.client.session)
        receipt = self.client.get(reverse('billing:receipt', args=[payment.reference]))
        self.assertContains(receipt, 'Discount (code LAUNCH50)')
        self.assertContains(receipt, 'Taxable amount')

    def test_unknown_and_invalid_codes_explain_why(self):
        response = self.client.post(self.url, {'promo_code': 'NOPE', 'apply_code': '1'}, follow=True)
        self.assertContains(response, 'recognise that code')
        make_code('EXPIRED', valid_until=timezone.localdate() - datetime.timedelta(days=1))
        response = self.client.post(self.url, {'promo_code': 'EXPIRED', 'apply_code': '1'}, follow=True)
        self.assertContains(response, 'expired')

    def test_remove_code(self):
        self.client.post(self.url, {'promo_code': 'LAUNCH50', 'apply_code': '1'})
        response = self.client.post(self.url, {'remove_code': '1'})
        self.assertNotContains(response, 'Discount (LAUNCH50)')

    def test_code_that_stopped_working_is_not_charged(self):
        self.client.post(self.url, {'promo_code': 'LAUNCH50', 'apply_code': '1'})
        PromoCode.objects.filter(pk=self.code.pk).update(is_active=False)
        self.client.post(self.url, {})
        payment = Payment.objects.get()
        self.assertIsNone(payment.promo_code)
        self.assertEqual(payment.subtotal, Decimal('499.00'))

    def test_full_discount_grants_without_payment(self):
        make_code('FREE100', percent_off=100)
        self.client.post(self.url, {'promo_code': 'FREE100', 'apply_code': '1'})
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Payment.objects.exists())
        self.assertTrue(UserSubscription.objects.filter(user=self.user, payment_reference='PROMO-FREE100').exists())
        self.assertEqual(PromoRedemption.objects.get().discount_amount, Decimal('499.00'))

    def test_article_and_course_checkouts(self):
        article = Article.objects.create(title='Special', slug='special', status=Article.Status.PUBLISHED,
                                         access_type=Article.AccessType.PAY_PER_ARTICLE, price=Decimal('100'))
        make_code('ARTICLE20', percent_off=20, applies_to_subscriptions=False, applies_to_articles=True)
        url = reverse('billing:purchase_checkout', args=[article.slug])
        self.client.post(url, {'promo_code': 'ARTICLE20', 'apply_code': '1'})
        self.client.post(url, {})
        self.assertEqual(Payment.objects.get(article=article).subtotal, Decimal('80.00'))
        self.assertTrue(ArticlePurchase.objects.filter(user=self.user, article=article).exists())

        course = TrainingCourse.objects.create(title='Course', description='d', price=Decimal('2000'), duration='1 week',
                                               instructor='I')
        make_code('TRAIN', percent_off=None, amount_off=Decimal('500'), applies_to_subscriptions=False,
                  applies_to_courses=True)
        url = reverse('training:course_checkout', args=[course.pk])
        self.client.post(url, {'promo_code': 'TRAIN', 'apply_code': '1'})
        self.client.post(url, {})
        self.assertEqual(Payment.objects.get(course=course).subtotal, Decimal('1500.00'))
        self.assertEqual(Enrollment.objects.get(user=self.user, course=course).payment_status, 'paid')

    def test_redeem_link_carries_the_code_to_checkout(self):
        response = self.client.get(reverse('billing:redeem_code', args=['launch50']))
        self.assertRedirects(response, reverse('billing:plan_browse'))
        self.assertContains(self.client.get(self.url), 'Discount (LAUNCH50)')


@override_settings(**FONEPAY_TEST_SETTINGS)
class FonepayCheckoutTests(TestCase):
    def test_fonepay_charges_the_discounted_total_and_counts_the_use_only_when_paid(self):
        from . import payments

        user = make_user('reader@example.com')
        plan = make_plan(price=499)
        make_code()
        self.client.force_login(user)
        url = reverse('billing:subscribe_checkout', args=[plan.pk])
        self.client.post(url, {'promo_code': 'LAUNCH50', 'apply_code': '1'})
        with patch('billing.fonepay.generate_intent_qr', return_value={'qrMessage': 'QR'}) as qr:
            self.client.post(url, {})
        self.assertEqual(qr.call_args[0][0], Decimal('281.94'))
        payment = Payment.objects.get()
        self.assertEqual(payment.discount_amount, Decimal('249.50'))
        self.assertFalse(PromoRedemption.objects.exists())
        payments.complete_payment(payment)
        self.assertEqual(PromoRedemption.objects.get().payment, payment)


class TrialTests(TestCase):
    def setUp(self):
        self.plan = make_plan()
        self.code = make_code('TRY7', percent_off=None, trial_days=7, trial_plan=self.plan, kind=PromoCode.Kind.TRIAL,
                              applies_to_subscriptions=False, description='Launch week — try it free')
        self.url = reverse('billing:redeem_code', args=['try7'])

    def test_anonymous_sees_the_offer_and_sign_in_links(self):
        response = self.client.get(self.url)
        self.assertContains(response, '7 days of')
        self.assertContains(response, reverse('users:register'))

    def test_start_trial_once(self):
        user = make_user('reader@example.com')
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'START MY FREE TRIAL')
        self.client.post(reverse('billing:start_trial', args=['TRY7']))
        subscription = UserSubscription.objects.get(user=user)
        self.assertTrue(subscription.is_trial)
        self.assertEqual(subscription.end_date, timezone.localdate() + datetime.timedelta(days=7))
        self.assertFalse(Payment.objects.exists())
        self.client.post(reverse('billing:start_trial', args=['TRY7']))
        self.assertEqual(UserSubscription.objects.filter(user=user).count(), 1)
        self.assertContains(self.client.get(reverse('billing:account')), 'FREE TRIAL')

    def test_past_subscribers_cannot_take_a_trial(self):
        user = make_user('old@example.com')
        today = timezone.localdate()
        UserSubscription.objects.create(user=user, plan=self.plan, start_date=today - datetime.timedelta(days=60),
                                        end_date=today - datetime.timedelta(days=30))
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'haven’t subscribed before')
        with self.assertRaises(promotions.PromoError):
            promotions.redeem_trial(self.code, user)

    def test_unknown_code(self):
        response = self.client.post(reverse('billing:redeem'), {'code': 'NOPE'})
        self.assertContains(response, 'recognise that code')


class StaffTests(TestCase):
    def setUp(self):
        self.eic = make_user('eic@example.com', role=User.Role.EDITOR_IN_CHIEF)
        self.client.force_login(self.eic)
        self.plan = make_plan()

    def form_data(self, **extra):
        data = {'code': 'partner', 'kind': 'partner', 'partner_name': 'Nepal Medical Association', 'percent_off': 25,
                'applies_to_subscriptions': 'on', 'per_user_limit': 1, 'is_active': 'on'}
        data.update(extra)
        return data

    def test_create_with_single_use_copies(self):
        response = self.client.post(reverse('billing:manage_promo_create'), self.form_data(copies=3))
        self.assertRedirects(response, reverse('billing:manage_promo_list'))
        self.assertEqual(PromoCode.objects.count(), 4)
        copies = PromoCode.objects.exclude(code='PARTNER')
        self.assertTrue(all(c.code.startswith('PARTNER-') and c.max_redemptions == 1 for c in copies))

    def test_form_rules(self):
        two = PromoCodeForm(data=self.form_data(amount_off=100))
        self.assertFalse(two.is_valid())
        gmail = PromoCodeForm(data=self.form_data(email_domains='gmail.com'))
        self.assertFalse(gmail.is_valid())
        self.assertIn('email_domains', gmail.errors)
        trial = PromoCodeForm(data=self.form_data(percent_off='', trial_days=14))
        self.assertIn('trial_plan', trial.errors)
        trial = PromoCodeForm(data=self.form_data(percent_off='', trial_days=14, trial_plan=self.plan.pk))
        self.assertTrue(trial.is_valid(), trial.errors)
        code = trial.save()
        self.assertEqual(code.kind, PromoCode.Kind.TRIAL)
        self.assertTrue(code.new_subscribers_only)

    def test_list_edit_and_export(self):
        code = make_code()
        PromoRedemption.objects.create(code=code, user=make_user('r@example.com'), item='Subscription', discount_amount=10)
        self.assertContains(self.client.get(reverse('billing:manage_promo_list')), 'LAUNCH50')
        page = self.client.get(reverse('billing:manage_promo_update', args=[code.pk]))
        self.assertContains(page, '/redeem/LAUNCH50/')
        export = self.client.get(reverse('billing:manage_promo_export', args=[code.pk]))
        self.assertIn('r@example.com', export.content.decode())

    def test_readers_and_editors_cannot_manage_codes(self):
        self.client.force_login(make_user('ed@example.com', role=User.Role.EDITOR))
        self.assertEqual(self.client.get(reverse('billing:manage_promo_list')).status_code, 403)


class PrivacyTests(TestCase):
    def test_export_lists_codes_used(self):
        user = make_user('reader@example.com')
        PromoRedemption.objects.create(code=make_code(), user=user, item='Subscription', discount_amount=10)
        self.assertEqual(export_user_data(user)['promo_codes_used'][0]['code'], 'LAUNCH50')
