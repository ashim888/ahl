"""Fonepay below the checkout flow (billing/tests.py covers the flow itself):
the HTTP client — login, token cache, signed bodies, 401 retry, error
handling — and the payment-settling edge cases in billing/payments.py.

No test here talks to Fonepay: requests.request is patched throughout.
"""
import base64
import datetime
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from articles.models import Article
from training.models import Enrollment, TrainingCourse
from users.models import User

from . import fonepay, payments
from .models import ArticlePurchase, Payment, SubscriptionPlan, UserSubscription
from .tests import FONEPAY_TEST_SETTINGS, _test_private_key_b64

TEST_KEY, TEST_KEY_B64 = _test_private_key_b64()


def fake_response(status_code=200, data=None, text_only=False):
    """A stand-in for requests.Response."""
    response = MagicMock(status_code=status_code)
    if text_only:
        response.json.side_effect = ValueError('not json')
    else:
        response.json.return_value = data if data is not None else {}
    return response


@override_settings(**FONEPAY_TEST_SETTINGS, FONEPAY_PRIVATE_KEY=TEST_KEY_B64)
class FonepayClientTests(TestCase):
    """billing/fonepay.py against a patched requests.request."""

    def setUp(self):
        cache.clear()

    def _patch(self, *responses):
        return patch('billing.fonepay.requests.request', side_effect=list(responses))

    def test_is_configured_needs_every_setting(self):
        self.assertTrue(fonepay.is_configured())
        with self.settings(FONEPAY_TERMINAL_ID=''):
            self.assertFalse(fonepay.is_configured())

    def test_hex_encoded_key_is_accepted_too(self):
        from cryptography.hazmat.primitives import serialization

        der = TEST_KEY.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        with self.settings(FONEPAY_PRIVATE_KEY=der.hex()):
            signature = base64.b64decode(fonepay.sign('{}'))
        TEST_KEY.public_key().verify(signature, b'{}', padding.PKCS1v15(), hashes.SHA256())

    def test_login_sends_basic_auth_and_a_signature_of_the_exact_body(self):
        with self._patch(fake_response(data={'accessToken': 'abc', 'expiresIn': 3600})) as request:
            token = fonepay.access_token()
        self.assertEqual(token, 'Bearer abc')
        method, url = request.call_args.args
        kwargs = request.call_args.kwargs
        self.assertEqual((method, url), ('POST', 'https://fonepay.test/api/login'))
        self.assertEqual(kwargs['headers']['Authorization'], 'Basic ' + base64.b64encode(b'u:p').decode())
        self.assertEqual(kwargs['timeout'], fonepay.TIMEOUT_SECONDS)
        # The signature covers the bytes actually sent.
        signature = base64.b64decode(kwargs['headers']['signature'])
        TEST_KEY.public_key().verify(signature, kwargs['data'].encode(), padding.PKCS1v15(), hashes.SHA256())
        self.assertEqual(json.loads(kwargs['data']), {'username': 'u', 'password': 'p'})

    def test_token_is_cached_and_a_bearer_prefix_is_not_doubled(self):
        with self._patch(fake_response(data={'accessToken': 'Bearer xyz', 'expiresIn': 600})) as request:
            self.assertEqual(fonepay.access_token(), 'Bearer xyz')
            self.assertEqual(fonepay.access_token(), 'Bearer xyz')
        self.assertEqual(request.call_count, 1)

    def test_login_without_a_token_is_an_error(self):
        with self._patch(fake_response(data={'message': 'ok'})):
            with self.assertRaisesMessage(fonepay.FonepayError, 'no access token'):
                fonepay.access_token()

    def test_http_error_carries_fonepays_message(self):
        with self._patch(fake_response(400, {'message': 'Invalid terminal'})):
            with self.assertRaisesMessage(fonepay.FonepayError, 'HTTP 400): Invalid terminal'):
                fonepay.access_token()

    def test_non_json_response_is_an_error(self):
        with self._patch(fake_response(502, text_only=True)):
            with self.assertRaisesMessage(fonepay.FonepayError, 'non-JSON response (HTTP 502)'):
                fonepay.access_token()

    def test_network_failure_is_an_error_without_leaking_details(self):
        with self._patch(requests.ConnectionError('secret-host:443 refused')):
            with self.assertRaises(fonepay.FonepayError) as caught:
                fonepay.access_token()
        self.assertEqual(str(caught.exception), 'Could not reach Fonepay: ConnectionError')

    def test_generate_intent_qr_sends_the_documented_payload(self):
        with self._patch(
            fake_response(data={'accessToken': 't'}),
            fake_response(data={'qrMessage': 'QR', 'websocketId': 'wss://x'}),
        ) as request:
            data = fonepay.generate_intent_qr(Decimal('499.00'), bill_id='b' * 80, reference='REF123')
        self.assertEqual(data['qrMessage'], 'QR')
        method, url = request.call_args.args
        self.assertEqual((method, url), ('POST', 'https://fonepay.test/api/generate-intent-qr'))
        self.assertEqual(request.call_args.kwargs['headers']['Authorization'], 'Bearer t')
        body = json.loads(request.call_args.kwargs['data'])
        self.assertEqual(body, {
            'amount': 499.0, 'billId': 'b' * 50, 'terminalId': '1234567890123456',
            'paymentMode': 'QR', 'referenceLabel': 'REF123', 'qrType': 'INTENT_QR',
        })

    def test_expired_token_is_refreshed_once_on_401(self):
        with self._patch(
            fake_response(data={'accessToken': 'old'}),
            fake_response(401, {'message': 'expired'}),
            fake_response(data={'accessToken': 'new'}),
            fake_response(data={'paymentStatus': 'pending'}),
        ) as request:
            data = fonepay.payment_status('REF123')
        self.assertEqual(data['paymentStatus'], 'pending')
        self.assertEqual(request.call_count, 4)
        self.assertEqual(request.call_args.kwargs['headers']['Authorization'], 'Bearer new')

    def test_a_second_401_gives_up(self):
        with self._patch(
            fake_response(data={'accessToken': 'old'}),
            fake_response(401, {'message': 'expired'}),
            fake_response(data={'accessToken': 'new'}),
            fake_response(401, {'message': 'still no'}),
        ):
            with self.assertRaisesMessage(fonepay.FonepayError, 'HTTP 401'):
                fonepay.payment_status('REF123')

    def test_other_errors_are_not_retried(self):
        with self._patch(
            fake_response(data={'accessToken': 't'}),
            fake_response(500, {'message': 'boom'}),
        ) as request:
            with self.assertRaises(fonepay.FonepayError):
                fonepay.payment_status('REF123')
        self.assertEqual(request.call_count, 2)

    def test_bank_list_is_a_bodyless_get_and_cached_for_an_hour(self):
        banks = [{'bankName': 'Test Bank', 'intentScheme': 'TEST://pay'}]
        with self._patch(
            fake_response(data={'accessToken': 't'}),
            fake_response(data={'bankDetails': banks}),
        ) as request:
            self.assertEqual(fonepay.bank_list(), banks)
            self.assertEqual(fonepay.bank_list(), banks)
        self.assertEqual(request.call_count, 2)  # login + one bank list
        method, url = request.call_args.args
        self.assertEqual((method, url), ('GET', 'https://fonepay.test/api/banks/list'))
        self.assertIsNone(request.call_args.kwargs['data'])
        self.assertEqual(request.call_args.kwargs['headers']['paymentMode'], 'INTENT')

    def test_bank_list_tolerates_an_unexpected_shape(self):
        with self._patch(fake_response(data={'accessToken': 't'}), fake_response(data=[])):
            self.assertEqual(fonepay.bank_list(), [])

    def test_payment_status_asks_about_this_terminal_and_reference(self):
        with self._patch(fake_response(data={'accessToken': 't'}), fake_response(data={'paymentStatus': 'success'})) as request:
            fonepay.payment_status('REF9')
        self.assertTrue(request.call_args.args[1].endswith('/thirdPartyDynamicQrGetStatus'))
        self.assertEqual(json.loads(request.call_args.kwargs['data']), {'terminalId': '1234567890123456', 'referenceLabel': 'REF9'})


@override_settings(**FONEPAY_TEST_SETTINGS)
class PaymentSettlementTests(TestCase):
    """billing/payments.py edge cases: what each Fonepay answer does to a
    payment, and what each kind of payment grants."""

    def setUp(self):
        self.reader = User.objects.create_user(email='settle@example.com', password='pw', first_name='S', last_name='R')
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        self.article = Article.objects.create(
            title='Special report', slug='special-report', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.PAY_PER_ARTICLE, price=150, html_content='<p>x</p>',
        )
        self.course = TrainingCourse.objects.create(
            title='Bootcamp', description='x', price=2900, duration='2 weeks', instructor='Dr. X',
        )

    def _payment(self, **extra):
        data = {
            'user': self.reader, 'kind': Payment.Kind.SUBSCRIPTION, 'plan': self.plan, 'amount': Decimal('499.00'),
            'description': 'Monthly', 'expires_at': timezone.now() + datetime.timedelta(minutes=15),
        }
        data.update(extra)
        return Payment.objects.create(**data)

    def _status(self, **data):
        return patch('billing.fonepay.payment_status', return_value=data)

    def test_start_payment_rejects_a_response_without_a_qr(self):
        with patch('billing.fonepay.generate_intent_qr', return_value={'status': 'Success'}):
            with self.assertRaisesMessage(fonepay.FonepayError, 'did not return a QR'):
                payments.start_payment(self.reader, kind=Payment.Kind.SUBSCRIPTION, amount=Decimal('499'), description='x', plan=self.plan)
        self.assertFalse(Payment.objects.exists())

    def test_start_payment_accepts_the_alternative_field_names(self):
        with patch('billing.fonepay.generate_intent_qr', return_value={'qrString': 'QR2', 'thirdpartyQrWebSocketUrl': 'wss://y'}):
            payment = payments.start_payment(self.reader, kind=Payment.Kind.SUBSCRIPTION, amount=Decimal('499'), description='x', plan=self.plan)
        self.assertEqual((payment.qr_message, payment.websocket_url), ('QR2', 'wss://y'))

    def test_a_changed_price_starts_a_fresh_payment(self):
        self._payment()
        with patch('billing.fonepay.generate_intent_qr', return_value={'qrMessage': 'QR'}) as generate:
            payment = payments.start_payment(self.reader, kind=Payment.Kind.SUBSCRIPTION, amount=Decimal('599'), description='x', plan=self.plan)
        generate.assert_called_once()
        self.assertEqual(payment.amount, Decimal('599'))
        self.assertEqual(Payment.objects.count(), 2)

    def test_a_nearly_expired_open_payment_is_not_reused(self):
        self._payment(expires_at=timezone.now() + datetime.timedelta(minutes=1))
        with patch('billing.fonepay.generate_intent_qr', return_value={'qrMessage': 'QR'}) as generate:
            payments.start_payment(self.reader, kind=Payment.Kind.SUBSCRIPTION, amount=Decimal('499'), description='x', plan=self.plan)
        generate.assert_called_once()

    def test_fonepay_unreachable_leaves_the_payment_pending(self):
        payment = self._payment()
        with patch('billing.fonepay.payment_status', side_effect=fonepay.FonepayError('down')):
            payment = payments.verify_payment(payment)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertFalse(UserSubscription.objects.exists())

    def test_fonepay_unreachable_long_after_expiry_closes_it(self):
        payment = self._payment(expires_at=timezone.now() - datetime.timedelta(minutes=30))
        with patch('billing.fonepay.payment_status', side_effect=fonepay.FonepayError('down')):
            self.assertEqual(payments.verify_payment(payment).status, Payment.Status.EXPIRED)

    def test_failed_is_recorded_and_grants_nothing(self):
        payment = self._payment()
        with self._status(paymentStatus='FAILED'):
            payment = payments.verify_payment(payment)
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertIsNotNone(payment.completed_at)
        self.assertEqual(payment.gateway_response, {'paymentStatus': 'FAILED'})
        self.assertFalse(UserSubscription.objects.exists())

    def test_success_without_an_amount_is_never_granted(self):
        payment = self._payment()
        with self._status(paymentStatus='success'):
            self.assertEqual(payments.verify_payment(payment).status, Payment.Status.FAILED)
        self.assertFalse(UserSubscription.objects.exists())

    def test_requested_amount_is_accepted_when_total_is_missing(self):
        payment = self._payment()
        with self._status(paymentStatus='success', requestedAmount='499'):
            self.assertEqual(payments.verify_payment(payment).status, Payment.Status.SUCCESS)

    def test_pending_response_is_stored_for_staff(self):
        payment = self._payment()
        with self._status(paymentStatus='pending', note='waiting'):
            payments.verify_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.gateway_response['note'], 'waiting')

    def test_a_settled_payment_is_never_checked_again(self):
        payment = self._payment(status=Payment.Status.FAILED)
        with self._status(paymentStatus='success', totalTransactionAmount='499') as status:
            self.assertEqual(payments.verify_payment(payment).status, Payment.Status.FAILED)
        status.assert_not_called()

    def test_stale_copy_does_not_grant_twice(self):
        """Two checks raced: the second holds a stale PENDING copy of a
        payment the first already settled. The row lock re-reads it."""
        payment = self._payment()
        stale = Payment.objects.get(pk=payment.pk)
        with self._status(paymentStatus='success', totalTransactionAmount='499'):
            payments.verify_payment(payment)
            payments.verify_payment(stale)
        self.assertEqual(UserSubscription.objects.filter(user=self.reader).count(), 1)

    def test_article_payment_records_the_purchase(self):
        payment = self._payment(kind=Payment.Kind.ARTICLE, plan=None, article=self.article, amount=Decimal('150'))
        with self._status(paymentStatus='success', totalTransactionAmount='150'):
            payments.verify_payment(payment)
        purchase = ArticlePurchase.objects.get(user=self.reader, article=self.article)
        self.assertEqual(purchase.payment_reference, payment.reference)

    def test_course_payment_reactivates_a_cancelled_enrollment(self):
        enrollment = Enrollment.objects.create(
            user=self.reader, course=self.course, status=Enrollment.Status.CANCELLED,
            payment_status=Enrollment.PaymentStatus.PENDING,
        )
        payment = self._payment(kind=Payment.Kind.COURSE, plan=None, course=self.course, amount=Decimal('2900'))
        with self._status(paymentStatus='success', totalTransactionAmount='2900'):
            payments.verify_payment(payment)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.Status.ACTIVE)
        self.assertEqual(enrollment.payment_status, Enrollment.PaymentStatus.PAID)
        self.assertEqual(enrollment.payment_reference, payment.reference)

    def test_background_job_expires_day_old_payments_without_asking(self):
        old = self._payment()
        Payment.objects.filter(pk=old.pk).update(created_at=timezone.now() - datetime.timedelta(days=2))
        with self._status(paymentStatus='pending') as status:
            self.assertEqual(payments.verify_pending_payments(), 0)
        status.assert_not_called()
        self.assertEqual(Payment.objects.get(pk=old.pk).status, Payment.Status.EXPIRED)

    def test_success_and_retry_urls_for_each_kind(self):
        subscription = self._payment()
        article = self._payment(kind=Payment.Kind.ARTICLE, plan=None, article=self.article)
        course = self._payment(kind=Payment.Kind.COURSE, plan=None, course=self.course)
        self.assertEqual(payments.success_url(subscription), reverse('users:profile'))
        self.assertEqual(payments.success_url(article), reverse('articles:article_detail', args=[self.article.slug]))
        self.assertEqual(payments.success_url(course), reverse('training:course_detail', args=[self.course.pk]))
        self.assertEqual(payments.retry_url(subscription), reverse('billing:subscribe_checkout', args=[self.plan.pk]))
        self.assertEqual(payments.retry_url(article), reverse('billing:purchase_checkout', args=[self.article.slug]))
        self.assertEqual(payments.retry_url(course), reverse('training:course_checkout', args=[self.course.pk]))

    def test_str_shows_reference_and_status(self):
        payment = self._payment()
        self.assertEqual(str(payment), f'{payment.reference} — Monthly (Waiting for payment)')


@override_settings(**FONEPAY_TEST_SETTINGS)
class PaymentPageTests(TestCase):
    """/billing/pay/<reference>/ for each payment state."""

    def setUp(self):
        self.reader = User.objects.create_user(email='page@example.com', password='pw', first_name='P', last_name='G')
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        self.client.force_login(self.reader)

    def _payment(self, **extra):
        data = {
            'user': self.reader, 'kind': Payment.Kind.SUBSCRIPTION, 'plan': self.plan, 'amount': Decimal('499.00'),
            'description': 'Monthly', 'qr_message': 'QRDATA', 'expires_at': timezone.now() + datetime.timedelta(minutes=15),
        }
        data.update(extra)
        return Payment.objects.create(**data)

    def test_paid_payment_redirects_to_what_was_bought(self):
        payment = self._payment(status=Payment.Status.SUCCESS)
        response = self.client.get(reverse('billing:payment_page', args=[payment.reference]))
        self.assertRedirects(response, reverse('users:profile'), fetch_redirect_response=False)

    def test_bank_list_outage_still_shows_the_qr(self):
        payment = self._payment()
        with patch('billing.fonepay.bank_list', side_effect=fonepay.FonepayError('down')):
            response = self.client.get(reverse('billing:payment_page', args=[payment.reference]))
        self.assertContains(response, 'data-qr="QRDATA"')

    def test_expired_payment_is_checked_once_more_on_the_page(self):
        payment = self._payment(expires_at=timezone.now() - datetime.timedelta(minutes=1))
        with patch('billing.fonepay.payment_status', return_value={'paymentStatus': 'success', 'totalTransactionAmount': '499'}):
            response = self.client.get(reverse('billing:payment_page', args=[payment.reference]))
        self.assertRedirects(response, reverse('users:profile'), fetch_redirect_response=False)
        self.assertTrue(UserSubscription.objects.filter(user=self.reader).exists())

    def test_closed_payment_offers_a_retry_and_does_not_ask_for_banks(self):
        payment = self._payment(status=Payment.Status.FAILED)
        with patch('billing.fonepay.bank_list') as bank_list:
            response = self.client.get(reverse('billing:payment_page', args=[payment.reference]))
        bank_list.assert_not_called()
        self.assertContains(response, reverse('billing:subscribe_checkout', args=[self.plan.pk]))

    def test_anonymous_reader_is_sent_to_login(self):
        payment = self._payment()
        self.client.logout()
        response = self.client.get(reverse('billing:payment_page', args=[payment.reference]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_pay_per_article_checkout_goes_through_fonepay(self):
        article = Article.objects.create(
            title='Special', slug='special-fonepay', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.PAY_PER_ARTICLE, price=150, html_content='<p>x</p>',
        )
        with patch('billing.fonepay.generate_intent_qr', return_value={'qrMessage': 'QR'}) as generate:
            response = self.client.post(reverse('billing:purchase_checkout', args=[article.slug]))
        payment = Payment.objects.get(kind=Payment.Kind.ARTICLE)
        self.assertRedirects(response, reverse('billing:payment_page', args=[payment.reference]), fetch_redirect_response=False)
        self.assertEqual(generate.call_args.args[0], Decimal('150.00'))
        self.assertFalse(ArticlePurchase.objects.exists())

    def test_buyer_who_already_owns_the_article_is_not_charged_again(self):
        article = Article.objects.create(
            title='Owned', slug='owned-article', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.PAY_PER_ARTICLE, price=150, html_content='<p>x</p>',
        )
        ArticlePurchase.objects.create(user=self.reader, article=article, amount=150)
        with patch('billing.fonepay.generate_intent_qr') as generate:
            response = self.client.post(reverse('billing:purchase_checkout', args=[article.slug]))
        generate.assert_not_called()
        self.assertRedirects(response, reverse('articles:article_detail', args=[article.slug]), fetch_redirect_response=False)
