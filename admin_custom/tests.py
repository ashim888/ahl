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
from billing.models import ArticlePurchase, SubscriptionPlan, UserSubscription
from newsletter.models import Subscriber
from training.models import Enrollment, TrainingCourse
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


class AnalyticsCSVExportTests(TestCase):
    def test_editorial_staff_can_download_csv(self):
        self.client.force_login(make_editor())
        response = self.client.get(reverse('admin_custom:analytics_csv_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename="analytics-', response['Content-Disposition'])

    def test_reader_cannot_download_csv(self):
        self.client.force_login(make_reader())
        response = self.client.get(reverse('admin_custom:analytics_csv_export'))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse('admin_custom:analytics_csv_export'))
        self.assertEqual(response.status_code, 302)

    def test_csv_reflects_the_same_underlying_data_as_the_html_page(self):
        article = make_article()
        ArticleView.objects.create(article=article)
        ArticleView.objects.create(article=article)

        self.client.force_login(make_editor())
        response = self.client.get(reverse('admin_custom:analytics_csv_export'))
        content = response.content.decode()
        self.assertIn('Article Views (last 14 days)', content)
        self.assertIn(article.title, content)
        # download_count=2, citation_count=1 from make_article()
        self.assertIn(f'{article.title},2,2,1', content)

    def test_csv_is_valid_and_parses_into_rows(self):
        import csv
        import io

        self.client.force_login(make_editor())
        response = self.client.get(reverse('admin_custom:analytics_csv_export'))
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertGreater(len(rows), 10)
        self.assertEqual(rows[0], ['Article Views (last 14 days)'])


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
            sponsor_name='Sponsor', zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1, image=demo_ad_image(),
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


class RevenueAccessTests(TestCase):
    """access control is identical across all three revenue pages — one
    parametrized-by-hand class rather than three near-duplicate ones.
    """

    def test_editorial_staff_can_view_all_three_pages(self):
        self.client.force_login(make_editor())
        for name in ['admin_custom:revenue', 'admin_custom:revenue_training', 'admin_custom:revenue_subscriptions']:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_reader_cannot_view_any_revenue_page(self):
        self.client.force_login(make_reader())
        for name in ['admin_custom:revenue', 'admin_custom:revenue_training', 'admin_custom:revenue_subscriptions']:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 403, name)

    def test_anonymous_redirected_to_login_on_all_three_pages(self):
        for name in ['admin_custom:revenue', 'admin_custom:revenue_training', 'admin_custom:revenue_subscriptions']:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)


class RevenueTrainingViewTests(TestCase):
    def setUp(self):
        self.client.force_login(make_editor())

    def test_collected_pending_refunded_totals(self):
        course = TrainingCourse.objects.create(title='Course', description='D', price=50, duration='4 weeks', instructor='I')
        Enrollment.objects.create(user=make_reader('a@example.com'), course=course, payment_status=Enrollment.PaymentStatus.PAID)
        Enrollment.objects.create(user=make_reader('b@example.com'), course=course, payment_status=Enrollment.PaymentStatus.PENDING)
        Enrollment.objects.create(user=make_reader('c@example.com'), course=course, payment_status=Enrollment.PaymentStatus.REFUNDED)

        response = self.client.get(reverse('admin_custom:revenue_training'))
        self.assertEqual(response.context['collected_total'], 50)
        self.assertEqual(response.context['pending_total'], 50)
        self.assertEqual(response.context['refunded_total'], 50)
        self.assertEqual(response.context['enrollment_total'], 3)

    def test_revenue_trend_reflects_paid_enrollment_today(self):
        course = TrainingCourse.objects.create(title='Course', description='D', price=50, duration='4 weeks', instructor='I')
        Enrollment.objects.create(user=make_reader('a@example.com'), course=course, payment_status=Enrollment.PaymentStatus.PAID)

        response = self.client.get(reverse('admin_custom:revenue_training'))
        self.assertEqual(sum(d['count'] for d in response.context['revenue_trend']), 50)


class RevenueSubscriptionsViewTests(TestCase):
    def setUp(self):
        self.client.force_login(make_editor())

    def test_per_plan_breakdown_and_active_count(self):
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=30, duration_days=30,
        )
        UserSubscription.objects.create(
            user=make_reader('sub1@example.com'), plan=plan, status=UserSubscription.Status.ACTIVE,
            start_date=timezone.localdate(), end_date=timezone.localdate() + datetime.timedelta(days=10),
        )
        UserSubscription.objects.create(
            user=make_reader('sub2@example.com'), plan=plan, status=UserSubscription.Status.CANCELLED,
            start_date=timezone.localdate() - datetime.timedelta(days=40),
            end_date=timezone.localdate() - datetime.timedelta(days=10),
        )

        response = self.client.get(reverse('admin_custom:revenue_subscriptions'))
        self.assertEqual(response.context['active_subscription_count'], 1)
        self.assertEqual(response.context['cancelled_subscription_count'], 1)
        plans = list(response.context['plans'])
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].active_count, 1)
        self.assertEqual(plans[0].lifetime_count, 2)
        self.assertEqual(plans[0].lifetime_revenue, 60)

    def test_purchase_revenue_totals(self):
        article = Article.objects.create(
            title='Special', slug='special-article', abstract='A', article_type=Article.ArticleType.ORIGINAL_RESEARCH,
            status=Article.Status.PUBLISHED,
        )
        ArticlePurchase.objects.create(user=make_reader('buyer@example.com'), article=article, amount=5)

        response = self.client.get(reverse('admin_custom:revenue_subscriptions'))
        self.assertEqual(response.context['purchase_count'], 1)
        self.assertEqual(response.context['purchase_revenue'], 5)

    def test_revenue_trend_combines_subscriptions_and_purchases(self):
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=30, duration_days=30,
        )
        UserSubscription.objects.create(
            user=make_reader('sub@example.com'), plan=plan, status=UserSubscription.Status.ACTIVE,
            start_date=timezone.localdate(), end_date=timezone.localdate() + datetime.timedelta(days=10),
        )
        article = Article.objects.create(
            title='Special', slug='special-article-2', abstract='A', article_type=Article.ArticleType.ORIGINAL_RESEARCH,
            status=Article.Status.PUBLISHED,
        )
        ArticlePurchase.objects.create(user=make_reader('buyer2@example.com'), article=article, amount=5)

        response = self.client.get(reverse('admin_custom:revenue_subscriptions'))
        self.assertEqual(sum(d['count'] for d in response.context['revenue_trend']), 35)


class RevenueOverviewViewTests(TestCase):
    def setUp(self):
        self.client.force_login(make_editor())

    def test_totals_combine_training_subscriptions_and_purchases(self):
        course = TrainingCourse.objects.create(title='Course', description='D', price=50, duration='4 weeks', instructor='I')
        Enrollment.objects.create(user=make_reader('a@example.com'), course=course, payment_status=Enrollment.PaymentStatus.PAID)

        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=30, duration_days=30,
        )
        UserSubscription.objects.create(
            user=make_reader('sub@example.com'), plan=plan, status=UserSubscription.Status.ACTIVE,
            start_date=timezone.localdate(), end_date=timezone.localdate() + datetime.timedelta(days=10),
        )
        article = Article.objects.create(
            title='Special', slug='special-article-3', abstract='A', article_type=Article.ArticleType.ORIGINAL_RESEARCH,
            status=Article.Status.PUBLISHED,
        )
        ArticlePurchase.objects.create(user=make_reader('buyer3@example.com'), article=article, amount=5)

        response = self.client.get(reverse('admin_custom:revenue'))
        self.assertEqual(response.context['training_total'], 50)
        self.assertEqual(response.context['subscription_total'], 30)
        self.assertEqual(response.context['purchase_total'], 5)
        self.assertEqual(response.context['total_revenue'], 85)
        # 30-day plan at price 30 normalizes to exactly 30/month.
        self.assertEqual(response.context['mrr_estimate'], 30)

    def test_zero_state_does_not_error(self):
        response = self.client.get(reverse('admin_custom:revenue'))
        self.assertEqual(response.context['total_revenue'], 0)
        self.assertEqual(response.context['mrr_estimate'], 0)


def _comment_post_data(article, comment_text, **extra):
    """Same helper as articles/tests.py's ArticleCommentsTests — builds
    valid POST data (including the anti-spoofing content_type/object_pk/
    timestamp/security_hash fields) for django_comments's post_comment view.
    """
    from django_comments_xtd.forms import XtdCommentForm

    data = XtdCommentForm(article).initial.copy()
    data.update({
        'comment': comment_text, 'name': '', 'email': '', 'url': '',
        'reply_to': 0, 'followup': False, 'honeypot': '',
        'next': article.get_absolute_url(),
    })
    data.update(extra)
    return data


class CommentModerationTests(TestCase):
    def setUp(self):
        self.editor = make_editor(email='comment-mod-editor@example.com')
        self.reader = make_reader(email='comment-mod-reader@example.com')
        self.article = make_article(slug='commentable-for-moderation')
        self.client.force_login(self.reader)
        self.client.post(
            reverse('comments-post-comment'), _comment_post_data(self.article, 'A moderation test comment.'), follow=True,
        )
        from django_comments_xtd.models import XtdComment
        self.comment = XtdComment.objects.get(comment='A moderation test comment.')

    def test_reader_cannot_access_moderation_queue(self):
        response = self.client.get(reverse('admin_custom:manage_comment_list'))
        self.assertEqual(response.status_code, 403)

    def test_editor_sees_comment_in_queue(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('admin_custom:manage_comment_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A moderation test comment.')

    def test_editor_can_remove_and_restore_a_comment(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('admin_custom:manage_comment_moderate', args=[self.comment.pk, 'remove']))
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.is_removed)

        self.client.post(reverse('admin_custom:manage_comment_moderate', args=[self.comment.pk, 'restore']))
        self.comment.refresh_from_db()
        self.assertFalse(self.comment.is_removed)

    def test_reader_cannot_moderate(self):
        response = self.client.post(reverse('admin_custom:manage_comment_moderate', args=[self.comment.pk, 'remove']))
        self.assertEqual(response.status_code, 403)

    def test_filters_by_removed_status(self):
        self.comment.is_removed = True
        self.comment.save(update_fields=['is_removed'])
        self.client.force_login(self.editor)

        response = self.client.get(reverse('admin_custom:manage_comment_list'), {'status': 'visible'})
        self.assertEqual(list(response.context['comments']), [])

        response = self.client.get(reverse('admin_custom:manage_comment_list'), {'status': 'removed'})
        self.assertEqual(list(response.context['comments']), [self.comment])
