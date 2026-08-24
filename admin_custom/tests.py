import datetime
import io

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from ads.models import AdSlot
from ads.services import record_click, record_impression
from articles.models import Article, ArticleView
from billing.models import SubscriptionPlan, UserSubscription
from newsletter.models import Subscriber
from users.models import User


def make_editor(email='analytics-editor@example.com'):
    return User.objects.create_user(email=email, password='pw', first_name='E', last_name='D', role=User.Role.EDITOR)


def make_reader(email='analytics-reader@example.com'):
    return User.objects.create_user(email=email, password='pw', first_name='R', last_name='D')


def make_article(slug='analytics-article'):
    return Article.objects.create(
        title='Analytics Article', slug=slug, abstract='Abstract',
        article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
        download_count=2, citation_count=1,
    )


def demo_ad_image():
    buffer = io.BytesIO()
    Image.new('RGB', (10, 10)).save(buffer, format='JPEG')
    return ContentFile(buffer.getvalue(), name='ad.jpg')


class AnalyticsAccessTests(TestCase):
    def test_editorial_staff_can_view_analytics(self):
        self.client.force_login(make_editor())
        response = self.client.get(reverse('admin_custom:analytics'))
        self.assertEqual(response.status_code, 200)

    def test_reader_cannot_view_analytics(self):
        self.client.force_login(make_reader())
        response = self.client.get(reverse('admin_custom:analytics'))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse('admin_custom:analytics'))
        self.assertEqual(response.status_code, 302)


class AnalyticsDataTests(TestCase):
    def setUp(self):
        self.client.force_login(make_editor())

    def test_article_views_are_counted_in_trend_and_top_articles(self):
        article = make_article()
        ArticleView.objects.create(article=article)
        ArticleView.objects.create(article=article)

        response = self.client.get(reverse('admin_custom:analytics'))
        self.assertEqual(response.context['article_views_window_total'], 2)
        top = response.context['top_articles']
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].recent_views, 2)
        self.assertEqual(response.context['lifetime_downloads'], 2)
        self.assertEqual(response.context['lifetime_citations'], 1)

    def test_active_subscription_counted_and_mrr_estimated(self):
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=30, duration_days=30,
        )
        reader = make_reader('subscriber@example.com')
        UserSubscription.objects.create(
            user=reader, plan=plan, status=UserSubscription.Status.ACTIVE,
            start_date=timezone.localdate(), end_date=timezone.localdate() + datetime.timedelta(days=10),
        )

        response = self.client.get(reverse('admin_custom:analytics'))
        self.assertEqual(response.context['active_subscription_count'], 1)
        # 30-day plan at price 30 normalizes to exactly 30/month.
        self.assertEqual(response.context['mrr_estimate'], 30)
        self.assertEqual(len(response.context['subscription_breakdown']), 1)

    def test_expired_subscription_not_counted_as_active(self):
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=30, duration_days=30,
        )
        reader = make_reader('expired-subscriber@example.com')
        UserSubscription.objects.create(
            user=reader, plan=plan, status=UserSubscription.Status.ACTIVE,
            start_date=timezone.localdate() - datetime.timedelta(days=40),
            end_date=timezone.localdate() - datetime.timedelta(days=10),
        )

        response = self.client.get(reverse('admin_custom:analytics'))
        self.assertEqual(response.context['active_subscription_count'], 0)

    def test_ad_totals_and_top_ads(self):
        ad = AdSlot.objects.create(
            sponsor_name='Sponsor', zone=AdSlot.Zone.HOMEPAGE, image=demo_ad_image(),
            link_url='https://example.com',
        )
        record_impression(ad)
        record_impression(ad)
        record_click(ad)

        response = self.client.get(reverse('admin_custom:analytics'))
        self.assertEqual(response.context['ads_all_time_impressions'], 2)
        self.assertEqual(response.context['ads_all_time_clicks'], 1)
        self.assertEqual(response.context['ads_all_time_ctr'], 50.0)
        self.assertEqual(response.context['ads_window_impressions'], 2)
        self.assertEqual(response.context['ads_window_clicks'], 1)
        self.assertEqual(list(response.context['top_ads']), [ad])

    def test_newsletter_breakdown_counts_confirmed_subscribers(self):
        Subscriber.objects.create(email='confirmed@example.com', status=Subscriber.Status.CONFIRMED, confirmed_at=timezone.now())
        Subscriber.objects.create(email='pending@example.com', status=Subscriber.Status.PENDING)

        response = self.client.get(reverse('admin_custom:analytics'))
        self.assertEqual(response.context['newsletter_total'], 2)
        self.assertEqual(response.context['newsletter_confirmed_count'], 1)
        self.assertEqual(sum(d['count'] for d in response.context['newsletter_confirmed_trend']), 1)
