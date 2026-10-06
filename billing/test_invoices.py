"""Nepali VAT invoices: numbering per fiscal year (Shrawan 1), BS and AD
dates, and the buyer's PAN."""
import datetime
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from users.models import User

from . import payments
from .models import Organization, Payment, SubscriptionPlan
from .nepali import fiscal_year, format_bs, format_invoice_date

STUB = override_settings(PAYMENT_GATEWAY='stub')


def at(year, month, day, hour=12):
    return timezone.make_aware(datetime.datetime(year, month, day, hour))


class NepaliCalendarTests(TestCase):
    def test_fiscal_year_turns_on_shrawan_first(self):
        # Shrawan 1, 2083 BS = 17 July 2026.
        self.assertEqual(fiscal_year(datetime.date(2026, 7, 16)), '2082-83')
        self.assertEqual(fiscal_year(datetime.date(2026, 7, 17)), '2083-84')
        self.assertEqual(fiscal_year(datetime.date(2027, 4, 1)), '2083-84')

    def test_bs_and_ad_dates(self):
        self.assertEqual(format_bs(datetime.date(2026, 10, 6)), '20 Aswin 2083')
        moment = at(2026, 10, 6)
        self.assertEqual(format_invoice_date(moment), '6 October 2026 (20 Aswin 2083 BS)')
        with self.settings(INVOICE_DATE_DISPLAY='ad'):
            self.assertEqual(format_invoice_date(moment), '6 October 2026')
        with self.settings(INVOICE_DATE_DISPLAY='bs'):
            self.assertEqual(format_invoice_date(moment), '20 Aswin 2083 BS')


class FiscalYearNumberingTests(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(email='fy@example.com', password='pw', first_name='F', last_name='Y')
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )

    def _paid_on(self, moment):
        payment = Payment(
            user=self.reader, kind=Payment.Kind.SUBSCRIPTION, plan=self.plan, subtotal=499, vat_amount=Decimal('64.87'),
            amount=Decimal('563.87'), description='x', expires_at=moment, completed_at=moment, gateway=Payment.Gateway.STUB,
        )
        return payments.complete_payment(payment, grant=False)

    def test_numbers_restart_each_fiscal_year(self):
        numbers = [self._paid_on(moment).receipt_number for moment in (
            at(2026, 7, 10), at(2026, 7, 15), at(2026, 7, 17), at(2026, 8, 1),
        )]
        self.assertEqual(numbers, [
            'AHL-2082-83-000001', 'AHL-2082-83-000002', 'AHL-2083-84-000001', 'AHL-2083-84-000002',
        ])

    def test_credit_notes_follow_the_refund_date(self):
        payment = self._paid_on(at(2026, 7, 10))
        refunded = payments.refund_payment(payment, by=None, reason='x')
        self.assertTrue(refunded.credit_note_number.startswith(f'AHL-CN-{fiscal_year()}-'))


@STUB
class BuyerPanTests(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(email='pan@example.com', password='pw', first_name='P', last_name='N')
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        self.client.force_login(self.reader)
        self.url = reverse('billing:subscribe_checkout', args=[self.plan.pk])

    def test_pan_is_optional_and_printed_on_the_tax_invoice(self):
        self.assertContains(self.client.get(self.url), 'name="buyer_pan"')
        self.client.post(self.url, {'buyer_pan': '600 123 456'})
        payment = Payment.objects.get()
        self.assertEqual(payment.buyer_pan, '600123456')
        with self.settings(BUSINESS_PAN='300987654'):
            receipt = self.client.get(reverse('billing:receipt', args=[payment.reference]))
        self.assertContains(receipt, 'TAX INVOICE')
        self.assertContains(receipt, 'PAN / VAT no. 600123456')
        self.assertContains(receipt, 'BS)')

    def test_no_seller_pan_means_a_plain_receipt(self):
        self.client.post(self.url)
        receipt = self.client.get(reverse('billing:receipt', args=[Payment.objects.get().reference]))
        self.assertContains(receipt, 'RECEIPT')
        self.assertNotContains(receipt, 'TAX INVOICE')

    def test_bad_pan_is_refused_without_charging(self):
        response = self.client.post(self.url, {'buyer_pan': '12345'}, follow=True)
        self.assertContains(response, 'A PAN is 9 digits.')
        self.assertFalse(Payment.objects.exists())

    def test_last_pan_is_prefilled(self):
        self.client.post(self.url, {'buyer_pan': '600123456'})
        self.assertContains(self.client.get(self.url), 'value="600123456"')

    def test_organization_pan_goes_on_its_invoices(self):
        institutional = SubscriptionPlan.objects.create(
            name='Institutional', plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL, price=50000, duration_days=365,
        )
        org = Organization.objects.create(
            name='NHRC', email_domains='nhrc.gov.np', plan=institutional, pan='601234567',
            end_date=timezone.localdate() + datetime.timedelta(days=300), contact_email='accounts@nhrc.gov.np',
        )
        payment = payments.record_paid_payment(
            organization=org, kind=Payment.Kind.INSTITUTIONAL, plan=institutional, total_paid='56500',
            description='Institutional', gateway=Payment.Gateway.MANUAL, grant=False,
        )
        self.assertEqual(payment.buyer_pan, '601234567')
