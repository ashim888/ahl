"""Billing staff screens (/manage/billing/...): plans, subscriptions and
purchases — what senior staff can change, and that editors can't."""
import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from articles.models import Article
from users.models import User

from .access import (
    consume_free_sample, free_sample_reads_used, get_existing_article_gift, user_has_active_subscription,
)
from .models import (
    ArticleGift, ArticlePurchase, MeteredArticleRead, PlanFeature, SubscriptionPlan, UserSubscription,
)
from .money import format_money


class BillingStaffScreenTests(TestCase):
    def setUp(self):
        self.eic = User.objects.create_user(
            email='eic-billing@example.com', password='pw', first_name='E', last_name='C', role=User.Role.EDITOR_IN_CHIEF,
        )
        self.editor = User.objects.create_user(
            email='editor-billing@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='reader-billing@example.com', password='pw', first_name='R', last_name='B')
        self.monthly = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        self.institutional = SubscriptionPlan.objects.create(
            name='Hospital', plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL, price=25000, duration_days=365,
            is_active=False,
        )
        self.client.force_login(self.eic)

    def test_plan_list_filters_by_type_and_active(self):
        url = reverse('billing:manage_plan_list')
        by_type = self.client.get(url, {'plan_type': SubscriptionPlan.PlanType.INSTITUTIONAL})
        self.assertEqual(list(by_type.context['object_list']), [self.institutional])
        self.assertEqual(list(self.client.get(url, {'active': 'yes'}).context['object_list']), [self.monthly])
        self.assertEqual(list(self.client.get(url, {'active': 'no'}).context['object_list']), [self.institutional])

    def test_plan_edit_page_and_save(self):
        url = reverse('billing:manage_plan_update', args=[self.monthly.pk])
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context['is_create'])
        response = self.client.post(url, {
            'name': 'Monthly Plus', 'plan_type': self.monthly.plan_type, 'price': '599', 'duration_days': 30,
            'description': '', 'gift_articles_per_month': 0, 'is_active': 'on',
        }, follow=True)
        self.assertContains(response, '&quot;Monthly Plus&quot; updated.')
        self.monthly.refresh_from_db()
        self.assertEqual((self.monthly.name, str(self.monthly.price)), ('Monthly Plus', '599.00'))

    def test_plan_toggle_flips_active_and_needs_post(self):
        url = reverse('billing:manage_plan_toggle_active', args=[self.monthly.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.monthly.refresh_from_db()
        self.assertFalse(self.monthly.is_active)
        self.client.post(url)
        self.monthly.refresh_from_db()
        self.assertTrue(self.monthly.is_active)

    def test_revoke_cancels_the_subscription(self):
        subscription = UserSubscription.objects.create(
            user=self.reader, plan=self.monthly, end_date=timezone.localdate() + datetime.timedelta(days=30),
        )
        self.assertTrue(user_has_active_subscription(self.reader))
        response = self.client.post(reverse('billing:manage_subscription_revoke', args=[subscription.pk]))
        self.assertRedirects(response, reverse('billing:manage_subscription_list'), fetch_redirect_response=False)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, UserSubscription.Status.CANCELLED)
        self.assertFalse(user_has_active_subscription(self.reader))

    def test_grant_purchase_gives_the_reader_the_article(self):
        article = Article.objects.create(
            title='Special', slug='granted-special', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.PAY_PER_ARTICLE, price=150,
        )
        response = self.client.post(reverse('billing:manage_purchase_grant'), {
            'user': self.reader.pk, 'article': article.pk, 'amount': '0',
        }, follow=True)
        self.assertContains(response, 'purchase of &quot;Special&quot;')
        self.assertTrue(ArticlePurchase.objects.filter(user=self.reader, article=article).exists())

    def test_editors_cannot_touch_money_screens(self):
        subscription = UserSubscription.objects.create(
            user=self.reader, plan=self.monthly, end_date=timezone.localdate() + datetime.timedelta(days=30),
        )
        self.client.force_login(self.editor)
        for url in (
            reverse('billing:manage_plan_toggle_active', args=[self.monthly.pk]),
            reverse('billing:manage_subscription_revoke', args=[subscription.pk]),
            reverse('billing:manage_purchase_grant'),
        ):
            self.assertEqual(self.client.post(url).status_code, 403, url)
        self.monthly.refresh_from_db()
        subscription.refresh_from_db()
        self.assertTrue(self.monthly.is_active)
        self.assertEqual(subscription.status, UserSubscription.Status.ACTIVE)

    def test_readers_are_sent_to_login_or_refused(self):
        self.client.logout()
        response = self.client.post(reverse('billing:manage_plan_toggle_active', args=[self.monthly.pk]))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse('billing:manage_plan_list')).status_code, 403)


class BillingModelAndHelperTests(TestCase):
    """The small pieces: labels staff see, and helpers' anonymous paths."""

    def setUp(self):
        self.reader = User.objects.create_user(email='helpers@example.com', password='pw', first_name='H', last_name='R')
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=499, duration_days=30,
        )
        self.article = Article.objects.create(
            title='Metered', slug='metered-article', status=Article.Status.PUBLISHED,
            access_type=Article.AccessType.SUBSCRIPTION,
        )

    def test_model_labels(self):
        feature = PlanFeature.objects.create(label='Ad-free reading')
        subscription = UserSubscription.objects.create(user=self.reader, plan=self.plan, end_date=timezone.localdate())
        purchase = ArticlePurchase.objects.create(user=self.reader, article=self.article, amount=0)
        gift = ArticleGift.objects.create(
            gifter=self.reader, article=self.article, period='2026-10', expires_at=timezone.now() + datetime.timedelta(days=7),
        )
        read = MeteredArticleRead.objects.create(session_key='abcdefgh12345', article=self.article, period='2026-10')
        self.assertEqual(str(feature), 'Ad-free reading')
        self.assertEqual(str(subscription), f'{self.reader} — {self.plan}')
        self.assertEqual(str(purchase), f'{self.reader} bought {self.article}')
        self.assertEqual(str(gift), f'{self.reader} gifted {self.article}')
        self.assertEqual(str(read), f'session abcdefgh read {self.article} free (2026-10)')

    def test_format_money_ignores_non_numbers_and_keeps_the_sign(self):
        self.assertEqual(format_money(''), '')
        self.assertEqual(format_money('abc'), '')
        self.assertEqual(format_money(-1500), '-Rs. 1,500')

    def test_anonymous_helpers_grant_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(user_has_active_subscription(AnonymousUser()))
        self.assertIsNone(get_existing_article_gift(AnonymousUser(), self.article))

    def test_sessionless_anonymous_reader_has_used_no_free_reads(self):
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.sessions.backends.db import SessionStore
        from django.test import RequestFactory

        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        request.session = SessionStore()
        self.assertEqual(free_sample_reads_used(request), 0)
        # The first free read creates the session it is counted against.
        self.assertTrue(consume_free_sample(request, self.article))
        self.assertTrue(request.session.session_key)
        self.assertEqual(free_sample_reads_used(request), 1)
