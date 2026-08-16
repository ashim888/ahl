import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from articles.models import Article
from users.models import User

from .access import article_is_accessible
from .models import ArticlePurchase, SubscriptionPlan, UserSubscription


def make_article(access_type, price=None, status=Article.Status.PUBLISHED):
    return Article.objects.create(
        title='Test Article', slug=f'test-article-{access_type}', abstract='Abstract',
        article_type=Article.ArticleType.NEWS_COMMENTARY, access_type=access_type, price=price, status=status,
    )


class ArticleAccessGateTests(TestCase):
    """billing.access.article_is_accessible is the real paywall gate — these
    cover each tier for anonymous, plain, subscribed, purchasing, and
    editorial-staff readers.
    """

    def setUp(self):
        self.reader = User.objects.create_user(
            email='reader@example.com', password='pw', first_name='R', last_name='D',
        )
        self.editor = User.objects.create_user(
            email='editor@example.com', password='pw', first_name='E', last_name='D',
            role=User.Role.EDITOR,
        )
        from django.contrib.auth.models import AnonymousUser
        self.anon = AnonymousUser()

    def test_open_access_is_always_accessible(self):
        article = make_article(Article.AccessType.OPEN_ACCESS)
        self.assertTrue(article_is_accessible(self.anon, article))
        self.assertTrue(article_is_accessible(self.reader, article))

    def test_subscription_article_blocked_without_subscription(self):
        article = make_article(Article.AccessType.SUBSCRIPTION)
        self.assertFalse(article_is_accessible(self.anon, article))
        self.assertFalse(article_is_accessible(self.reader, article))

    def test_subscription_article_open_with_active_subscription(self):
        article = make_article(Article.AccessType.SUBSCRIPTION)
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=5, duration_days=30,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=self.reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.assertTrue(article_is_accessible(self.reader, article))

    def test_expired_subscription_does_not_grant_access(self):
        article = make_article(Article.AccessType.SUBSCRIPTION)
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=5, duration_days=30,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=self.reader, plan=plan,
            start_date=today - datetime.timedelta(days=60), end_date=today - datetime.timedelta(days=30),
        )
        self.assertFalse(article_is_accessible(self.reader, article))

    def test_pay_per_article_blocked_without_purchase(self):
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=2)
        self.assertFalse(article_is_accessible(self.reader, article))

    def test_pay_per_article_open_after_purchase(self):
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=2)
        ArticlePurchase.objects.create(user=self.reader, article=article, amount=2)
        self.assertTrue(article_is_accessible(self.reader, article))

    def test_editorial_staff_always_has_access(self):
        subscription_article = make_article(Article.AccessType.SUBSCRIPTION)
        special_article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=2)
        self.assertTrue(article_is_accessible(self.editor, subscription_article))
        self.assertTrue(article_is_accessible(self.editor, special_article))

    def test_active_subscriber_can_read_pay_per_article_without_separate_purchase(self):
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=2)
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=5, duration_days=30,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=self.reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.assertTrue(article_is_accessible(self.reader, article))


class ArticleDetailPaywallViewTests(TestCase):
    """End-to-end: the public article detail view actually applies the gate."""

    def test_subscription_article_hides_full_text_from_anonymous_reader(self):
        article = make_article(Article.AccessType.SUBSCRIPTION)
        article.html_content = 'Secret full text'
        article.save()
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertNotContains(response, 'Secret full text')

    def test_subscription_article_shows_full_text_to_active_subscriber(self):
        article = make_article(Article.AccessType.SUBSCRIPTION)
        article.html_content = 'Secret full text'
        article.save()
        reader = User.objects.create_user(email='sub@example.com', password='pw', first_name='S', last_name='B')
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=5, duration_days=30,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.client.force_login(reader)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, 'Secret full text')


class GrantSubscriptionViewTests(TestCase):
    """The manual-grant flow that stands in for Stripe checkout today."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='pw', first_name='A', last_name='D', role=User.Role.ADMIN,
        )
        self.reader = User.objects.create_user(
            email='reader2@example.com', password='pw', first_name='R', last_name='D',
        )
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=5, duration_days=30,
        )

    def test_admin_can_grant_subscription(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('billing:manage_subscription_grant'), {'user': self.reader.pk, 'plan': self.plan.pk},
        )
        self.assertEqual(response.status_code, 302)
        subscription = UserSubscription.objects.get(user=self.reader, plan=self.plan)
        self.assertTrue(subscription.is_currently_active)
        self.assertEqual(subscription.end_date, timezone.localdate() + datetime.timedelta(days=30))

    def test_non_senior_staff_cannot_grant_subscription(self):
        editor = User.objects.create_user(
            email='editor2@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(editor)
        response = self.client.post(
            reverse('billing:manage_subscription_grant'), {'user': self.reader.pk, 'plan': self.plan.pk},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserSubscription.objects.filter(user=self.reader).exists())
