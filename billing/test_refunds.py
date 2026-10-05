"""Second billing batch: refunds that take access back, payments flagged for
staff instead of crashing (paid twice, course over capacity), and seats held
while someone is paying."""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from articles.models import Article
from training.models import Enrollment, TrainingCourse
from users.models import User

from . import payments
from .access import article_is_accessible, user_has_active_subscription
from .models import ArticlePurchase, Payment, SubscriptionPlan, UserSubscription
from .tests import FONEPAY_TEST_SETTINGS


def make_user(email, **extra):
    return User.objects.create_user(email=email, password='pw', first_name='Hari', last_name='Bista', **extra)


def paid(user, kind, price, **items):
    """A checkout payment that went through (the stub gateway's path)."""
    return payments.record_paid_payment(
        user=user, kind=kind, price=price, description='Test', gateway=Payment.Gateway.STUB, **items,
    )


class RefundTests(TestCase):
    def setUp(self):
        self.eic = make_user('eic-refunds@example.com', role=User.Role.EDITOR_IN_CHIEF)
        self.reader = make_user('refund-me@example.com')
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        self.client.force_login(self.eic)

    def _refund(self, payment, reason='Paid by mistake'):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('billing:manage_payment_refund', args=[payment.reference]), {'reason': reason})

    def test_refunding_a_subscription_ends_it_and_emails_a_credit_note(self):
        payment = paid(self.reader, Payment.Kind.SUBSCRIPTION, 499, plan=self.plan)
        self.assertTrue(user_has_active_subscription(self.reader))
        response = self._refund(payment)
        self.assertRedirects(response, reverse('billing:receipt', args=[payment.reference]), fetch_redirect_response=False)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertEqual((payment.refunded_by, payment.refund_reason), (self.eic, 'Paid by mistake'))
        self.assertEqual(payment.credit_note_number, 'AHL-CN-000001')
        self.assertFalse(user_has_active_subscription(self.reader))
        self.assertEqual(UserSubscription.objects.get(user=self.reader).status, UserSubscription.Status.CANCELLED)
        refund_email = mail.outbox[-1]
        self.assertEqual(refund_email.to, ['refund-me@example.com'])
        self.assertIn('AHL-CN-000001', refund_email.subject)
        self.assertIn('Total refunded: Rs. 563.87', refund_email.body)

    def test_refunding_an_article_purchase_locks_it_again(self):
        article = Article.objects.create(
            title='Special', slug='refund-special', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.PAY_PER_ARTICLE, price=150, html_content='<p>x</p>',
        )
        payment = paid(self.reader, Payment.Kind.ARTICLE, 150, article=article)
        self.assertTrue(article_is_accessible(self.reader, article))
        self._refund(payment)
        self.assertFalse(ArticlePurchase.objects.filter(user=self.reader).exists())
        self.assertFalse(article_is_accessible(self.reader, article))

    def test_refunding_a_course_cancels_the_enrollment(self):
        course = TrainingCourse.objects.create(title='Course', description='x', price=2900, duration='1 week', instructor='Dr. X')
        payment = paid(self.reader, Payment.Kind.COURSE, 2900, course=course)
        self._refund(payment)
        enrollment = Enrollment.objects.get(user=self.reader, course=course)
        self.assertEqual((enrollment.status, enrollment.payment_status), (Enrollment.Status.CANCELLED, Enrollment.PaymentStatus.REFUNDED))

    def test_a_staff_grant_paid_by_transfer_can_be_refunded_too(self):
        self.client.post(reverse('billing:manage_subscription_grant'), {
            'user': self.reader.pk, 'plan': self.plan.pk, 'amount_received': '563.87',
        })
        self._refund(Payment.objects.get())
        self.assertFalse(user_has_active_subscription(self.reader))

    def test_only_paid_payments_once_and_with_a_reason(self):
        payment = paid(self.reader, Payment.Kind.SUBSCRIPTION, 499, plan=self.plan)
        response = self.client.post(reverse('billing:manage_payment_refund', args=[payment.reference]), {'reason': ' '}, follow=True)
        self.assertContains(response, 'Say why it was refunded')
        self.assertEqual(Payment.objects.get(pk=payment.pk).status, Payment.Status.SUCCESS)
        self._refund(payment)
        response = self.client.post(reverse('billing:manage_payment_refund', args=[payment.reference]), {'reason': 'again'}, follow=True)
        self.assertContains(response, 'Only a paid payment can be refunded')
        self.assertEqual(Payment.objects.get(pk=payment.pk).credit_note_number, 'AHL-CN-000001')

    def test_credit_notes_and_receipts_are_separate_sequences(self):
        first = paid(self.reader, Payment.Kind.SUBSCRIPTION, 499, plan=self.plan)
        second = paid(make_user('second-refund@example.com'), Payment.Kind.SUBSCRIPTION, 499, plan=self.plan)
        self._refund(first)
        self._refund(second)
        numbers = sorted(Payment.objects.values_list('credit_note_number', flat=True))
        self.assertEqual(numbers, ['AHL-CN-000001', 'AHL-CN-000002'])
        self.assertEqual(sorted(Payment.objects.values_list('receipt_number', flat=True)), ['AHL-000001', 'AHL-000002'])

    def test_receipt_and_billing_page_show_the_refund(self):
        payment = paid(self.reader, Payment.Kind.SUBSCRIPTION, 499, plan=self.plan)
        receipt_url = reverse('billing:receipt', args=[payment.reference])
        self.assertContains(self.client.get(receipt_url), 'RECORD FULL REFUND')
        self._refund(payment)
        staff_view = self.client.get(receipt_url)
        self.assertNotContains(staff_view, 'RECORD FULL REFUND')
        self.client.force_login(self.reader)
        reader_view = self.client.get(receipt_url)
        self.assertContains(reader_view, 'CREDIT NOTE')
        self.assertContains(reader_view, 'AHL-CN-000001')
        self.assertNotContains(reader_view, 'Paid by mistake')  # staff-only panel
        self.assertContains(self.client.get(reverse('billing:account')), 'REFUNDED')

    def test_refunds_leave_revenue(self):
        payment = paid(self.reader, Payment.Kind.SUBSCRIPTION, 499, plan=self.plan)
        self._refund(payment)
        overview = self.client.get(reverse('admin_custom:revenue'))
        self.assertEqual(overview.context['subscription_total'], 0)
        self.assertEqual(overview.context['refunded_total'], Decimal('499.00'))

    def test_only_senior_staff_refund(self):
        payment = paid(self.reader, Payment.Kind.SUBSCRIPTION, 499, plan=self.plan)
        for user in (make_user('editor-refund@example.com', role=User.Role.EDITOR), self.reader):
            self.client.force_login(user)
            self.assertEqual(
                self.client.post(reverse('billing:manage_payment_refund', args=[payment.reference]), {'reason': 'x'}).status_code,
                403,
            )
        self.assertEqual(Payment.objects.get(pk=payment.pk).status, Payment.Status.SUCCESS)


class NeedsAttentionTests(TestCase):
    """Paid but couldn't be granted cleanly: never a crash, always a flag."""

    def setUp(self):
        self.reader = make_user('twice@example.com')
        self.article = Article.objects.create(
            title='Special', slug='twice-special', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.PAY_PER_ARTICLE, price=150,
        )

    def test_buying_an_owned_article_again_is_flagged_not_broken(self):
        paid(self.reader, Payment.Kind.ARTICLE, 150, article=self.article)
        second = paid(self.reader, Payment.Kind.ARTICLE, 150, article=self.article)
        self.assertEqual(second.status, Payment.Status.SUCCESS)
        self.assertIn('already owned', second.attention)
        self.assertEqual(ArticlePurchase.objects.filter(user=self.reader).count(), 1)

    @override_settings(**FONEPAY_TEST_SETTINGS)
    def test_two_fonepay_payments_for_the_same_article_both_settle(self):
        """Used to raise IntegrityError inside the status check, leaving a
        paid payment stuck as pending forever."""
        first, second = (
            Payment.objects.create(
                user=self.reader, kind=Payment.Kind.ARTICLE, article=self.article, subtotal=150, vat_amount=Decimal('19.50'),
                amount=Decimal('169.50'), description='x', expires_at=timezone.now() + datetime.timedelta(minutes=10),
            ) for _ in range(2)
        )
        with patch('billing.fonepay.payment_status', return_value={'paymentStatus': 'success', 'totalTransactionAmount': '169.50'}):
            payments.verify_payment(first)
            settled = payments.verify_payment(second)
        self.assertEqual(settled.status, Payment.Status.SUCCESS)
        self.assertTrue(settled.attention)

    def test_staff_find_and_clear_flagged_payments(self):
        paid(self.reader, Payment.Kind.ARTICLE, 150, article=self.article)
        flagged = paid(self.reader, Payment.Kind.ARTICLE, 150, article=self.article)
        self.client.force_login(make_user('eic-attention@example.com', role=User.Role.EDITOR_IN_CHIEF))
        listing = self.client.get(reverse('billing:manage_payment_list'), {'attention': '1'})
        self.assertEqual([p.pk for p in listing.context['payments']], [flagged.pk])
        self.assertEqual(listing.context['attention_count'], 1)
        self.assertContains(self.client.get(reverse('billing:receipt', args=[flagged.reference])), 'Needs a look')
        self.client.post(reverse('billing:manage_payment_handled', args=[flagged.reference]))
        self.assertEqual(Payment.objects.get(pk=flagged.pk).attention, '')

    def test_flagged_duplicate_refund_keeps_the_first_purchase(self):
        paid(self.reader, Payment.Kind.ARTICLE, 150, article=self.article)
        duplicate = paid(self.reader, Payment.Kind.ARTICLE, 150, article=self.article)
        payments.refund_payment(duplicate, by=None, reason='Paid twice')
        self.assertTrue(article_is_accessible(self.reader, self.article))
        self.assertEqual(Payment.objects.get(pk=duplicate.pk).attention, '')

    def test_paying_for_a_course_already_paid_for_is_flagged(self):
        course = TrainingCourse.objects.create(title='C', description='x', price=100, duration='1 week', instructor='I')
        paid(self.reader, Payment.Kind.COURSE, 100, course=course)
        second = paid(self.reader, Payment.Kind.COURSE, 100, course=course)
        self.assertIn('already enrolled', second.attention)

    def test_course_filled_while_paying_still_enrols_but_is_flagged(self):
        course = TrainingCourse.objects.create(
            title='C', description='x', price=100, duration='1 week', instructor='I', max_enrollments=1,
        )
        Enrollment.objects.create(user=make_user('first-seat@example.com'), course=course)
        late = paid(self.reader, Payment.Kind.COURSE, 100, course=course)
        self.assertIn('over capacity', late.attention)
        self.assertEqual(Enrollment.objects.get(user=self.reader).payment_status, Enrollment.PaymentStatus.PAID)


@override_settings(PAYMENT_GATEWAY='stub')
class SeatHoldTests(TestCase):
    def setUp(self):
        self.course = TrainingCourse.objects.create(
            title='Small class', description='x', price=100, duration='1 week', instructor='I', max_enrollments=1,
        )
        self.payer = make_user('paying@example.com')
        self.other = make_user('also-wants@example.com')

    def _open_checkout(self, user, minutes=10):
        return Payment.objects.create(
            user=user, kind=Payment.Kind.COURSE, course=self.course, subtotal=100, vat_amount=13, amount=113,
            description='x', expires_at=timezone.now() + datetime.timedelta(minutes=minutes),
        )

    def test_someone_paying_holds_the_last_seat(self):
        self._open_checkout(self.payer)
        self.assertEqual(payments.seats_taken(self.course), 1)
        self.client.force_login(self.other)
        response = self.client.post(reverse('training:course_checkout', args=[self.course.pk]), follow=True)
        self.assertContains(response, 'This course is full.')
        self.assertFalse(Enrollment.objects.filter(user=self.other).exists())
        self.assertEqual(response.context['spots_left'], 0)

    def test_your_own_open_checkout_doesnt_lock_you_out(self):
        self._open_checkout(self.payer)
        self.client.force_login(self.payer)
        self.client.post(reverse('training:course_checkout', args=[self.course.pk]))
        self.assertTrue(Enrollment.objects.filter(user=self.payer).exists())

    def test_an_abandoned_checkout_frees_the_seat(self):
        self._open_checkout(self.payer, minutes=-1)
        self.assertEqual(payments.seats_taken(self.course), 0)
        self.client.force_login(self.other)
        self.client.post(reverse('training:course_checkout', args=[self.course.pk]))
        self.assertTrue(Enrollment.objects.filter(user=self.other).exists())
