import datetime
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from articles.models import Article
from users.models import User

from .access import (
    FREE_SAMPLE_LIMIT_PER_MONTH, article_is_accessible, consume_free_sample, create_or_get_article_gift,
    free_sample_reads_used, get_valid_article_gift, gift_articles_remaining,
)
from .gateway import PaymentResult
from .models import ArticlePurchase, PlanFeature, SubscriptionPlan, UserSubscription
from .views import build_comparison_matrix


def make_article(access_type, price=None, status=Article.Status.PUBLISHED, slug_suffix=''):
    return Article.objects.create(
        title='Test Article', slug=f'test-article-{access_type}{slug_suffix}', abstract='Abstract',
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

    def test_pay_per_article_hides_full_text_from_anonymous_reader(self):
        # pay_per_article, not subscription — subscription-tier articles are
        # now metered (MeteredPaywallViewTests below covers that gate
        # specifically); pay_per_article stays a hard, unmetered paywall, so
        # it's the cleaner case for "the real entitlement gate itself blocks
        # a reader with no grant at all," independent of free-sample state.
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=2)
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


class PlanPerkEnforcementTests(TestCase):
    """SubscriptionPlan.grants_unlimited_articles/grants_ad_free_reading —
    the perk fields article_is_accessible/is_ad_free_reader actually check
    now, replacing the old "has any active subscription" blanket check that
    made every plan grant identical access regardless of price/type.
    """

    def setUp(self):
        self.reader = User.objects.create_user(
            email='perk-reader@example.com', password='pw', first_name='P', last_name='R',
        )

    def _subscribe(self, **plan_kwargs):
        plan = SubscriptionPlan.objects.create(
            name='Plan', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=5, duration_days=30,
            **plan_kwargs,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=self.reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        return plan

    def test_plan_without_unlimited_articles_perk_does_not_unlock_subscription_articles(self):
        self._subscribe(grants_unlimited_articles=False)
        article = make_article(Article.AccessType.SUBSCRIPTION)
        self.assertFalse(article_is_accessible(self.reader, article))

    def test_plan_without_unlimited_articles_perk_still_allows_a_separate_purchase(self):
        # grants_unlimited_articles only covers the subscription-tier
        # bypass — an ArticlePurchase is a distinct, per-article grant and
        # must keep working regardless of what the reader's plan enforces.
        self._subscribe(grants_unlimited_articles=False)
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=2)
        ArticlePurchase.objects.create(user=self.reader, article=article, amount=2)
        self.assertTrue(article_is_accessible(self.reader, article))

    def test_default_plan_still_grants_unlimited_articles(self):
        # Behavior-preserving default: every plan defaults both perk fields
        # to True, so existing/seeded plans keep today's access unchanged.
        self._subscribe()
        article = make_article(Article.AccessType.SUBSCRIPTION)
        self.assertTrue(article_is_accessible(self.reader, article))


class GiftArticleAccessTests(TestCase):
    """billing.access.gift_articles_remaining/create_or_get_article_gift/
    get_valid_article_gift — "gift articles" (ROADMAP.md Phase 10).
    """

    def setUp(self):
        self.reader = User.objects.create_user(
            email='gift-reader@example.com', password='pw', first_name='G', last_name='R',
        )

    def _subscribe(self, **plan_kwargs):
        plan = SubscriptionPlan.objects.create(
            name='Plan', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=5, duration_days=30,
            **plan_kwargs,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=self.reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        return plan

    def test_non_subscriber_has_zero_gifts_remaining(self):
        self.assertEqual(gift_articles_remaining(self.reader), 0)

    def test_default_plan_has_zero_gifts_remaining(self):
        # Default 0, unlike grants_unlimited_articles/grants_ad_free_reading
        # — gifting is a brand-new capability, no plan claims to grant it
        # until an editor sets an allowance.
        self._subscribe()
        self.assertEqual(gift_articles_remaining(self.reader), 0)

    def test_plan_with_allowance_reports_remaining(self):
        self._subscribe(gift_articles_per_month=3)
        self.assertEqual(gift_articles_remaining(self.reader), 3)

    def test_creating_a_gift_consumes_one_slot(self):
        self._subscribe(gift_articles_per_month=2)
        article = make_article(Article.AccessType.SUBSCRIPTION, slug_suffix='-gift-1')
        create_or_get_article_gift(self.reader, article)
        self.assertEqual(gift_articles_remaining(self.reader), 1)

    def test_regenerating_for_the_same_article_does_not_consume_a_second_slot(self):
        self._subscribe(gift_articles_per_month=2)
        article = make_article(Article.AccessType.SUBSCRIPTION, slug_suffix='-gift-2')
        first = create_or_get_article_gift(self.reader, article)
        second = create_or_get_article_gift(self.reader, article)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(gift_articles_remaining(self.reader), 1)

    def test_no_gift_created_once_allowance_is_used_up(self):
        self._subscribe(gift_articles_per_month=1)
        first = make_article(Article.AccessType.SUBSCRIPTION, slug_suffix='-gift-3')
        second = make_article(Article.AccessType.SUBSCRIPTION, slug_suffix='-gift-4')
        create_or_get_article_gift(self.reader, first)
        self.assertIsNone(create_or_get_article_gift(self.reader, second))

    def test_pay_per_article_is_not_giftable(self):
        self._subscribe(gift_articles_per_month=3)
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=2)
        self.assertIsNone(create_or_get_article_gift(self.reader, article))

    def test_open_access_is_not_giftable(self):
        self._subscribe(gift_articles_per_month=3)
        article = make_article(Article.AccessType.OPEN_ACCESS)
        self.assertIsNone(create_or_get_article_gift(self.reader, article))

    def test_get_valid_article_gift_returns_the_gift(self):
        self._subscribe(gift_articles_per_month=2)
        article = make_article(Article.AccessType.SUBSCRIPTION, slug_suffix='-gift-5')
        gift = create_or_get_article_gift(self.reader, article)
        self.assertEqual(get_valid_article_gift(article, gift.token), gift)

    def test_get_valid_article_gift_returns_none_for_wrong_token(self):
        self._subscribe(gift_articles_per_month=2)
        article = make_article(Article.AccessType.SUBSCRIPTION, slug_suffix='-gift-6')
        create_or_get_article_gift(self.reader, article)
        self.assertIsNone(get_valid_article_gift(article, 'not-a-real-token'))

    def test_get_valid_article_gift_returns_none_once_expired(self):
        self._subscribe(gift_articles_per_month=2)
        article = make_article(Article.AccessType.SUBSCRIPTION, slug_suffix='-gift-7')
        gift = create_or_get_article_gift(self.reader, article)
        gift.expires_at = timezone.now() - datetime.timedelta(days=1)
        gift.save(update_fields=['expires_at'])
        self.assertIsNone(get_valid_article_gift(article, gift.token))


class ArchivedArticleAccessTests(TestCase):
    """billing.access.article_is_accessible's ARCHIVED branch (ROADMAP.md
    Phase 10 Session 7) — an archived article requires grants_full_archive
    regardless of whatever access_type it had while still active, and is
    excluded from both the metered free-sample fallback and gifting (both
    would otherwise silently bypass the archive gate, since archiving
    doesn't touch access_type).
    """

    def setUp(self):
        self.reader = User.objects.create_user(
            email='archive-reader@example.com', password='pw', first_name='A', last_name='R',
        )

    def _subscribe(self, **plan_kwargs):
        plan = SubscriptionPlan.objects.create(
            name='Plan', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=5, duration_days=30,
            **plan_kwargs,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=self.reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        return plan

    def test_archived_article_blocked_without_the_perk(self):
        self._subscribe(grants_full_archive=False)
        article = make_article(Article.AccessType.OPEN_ACCESS, status=Article.Status.ARCHIVED, slug_suffix='-archive-1')
        self.assertFalse(article_is_accessible(self.reader, article))

    def test_archived_article_open_access_does_not_bypass_the_perk(self):
        # The key behavior this session exists to fix: archiving doesn't
        # touch access_type, so a once-open_access article must not stay
        # free forever just because its access_type field never changed.
        article = make_article(Article.AccessType.OPEN_ACCESS, status=Article.Status.ARCHIVED, slug_suffix='-archive-2')
        self.assertFalse(article_is_accessible(self.reader, article))

    def test_archived_article_accessible_with_the_perk(self):
        self._subscribe(grants_full_archive=True)
        article = make_article(Article.AccessType.SUBSCRIPTION, status=Article.Status.ARCHIVED, slug_suffix='-archive-3')
        self.assertTrue(article_is_accessible(self.reader, article))

    def test_grants_unlimited_articles_alone_does_not_unlock_archive(self):
        # A plan can have grants_unlimited_articles=True (the default) and
        # grants_full_archive=False (also the default) at once — the two
        # perks are independent; unlimited *current* articles doesn't imply
        # unlimited *archived* ones.
        self._subscribe(grants_unlimited_articles=True, grants_full_archive=False)
        article = make_article(Article.AccessType.SUBSCRIPTION, status=Article.Status.ARCHIVED, slug_suffix='-archive-4')
        self.assertFalse(article_is_accessible(self.reader, article))

    def test_editorial_staff_always_sees_archived_articles(self):
        editor = User.objects.create_user(
            email='archive-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        article = make_article(Article.AccessType.OPEN_ACCESS, status=Article.Status.ARCHIVED, slug_suffix='-archive-5')
        self.assertTrue(article_is_accessible(editor, article))

    def test_archived_article_does_not_grant_a_free_sample(self):
        article = make_article(Article.AccessType.SUBSCRIPTION, status=Article.Status.ARCHIVED, slug_suffix='-archive-6')
        request = RequestFactory().get('/')
        request.user = self.reader
        self.assertFalse(consume_free_sample(request, article))

    def test_archived_article_cannot_be_gifted(self):
        self._subscribe(gift_articles_per_month=3)
        article = make_article(Article.AccessType.SUBSCRIPTION, status=Article.Status.ARCHIVED, slug_suffix='-archive-7')
        self.assertIsNone(create_or_get_article_gift(self.reader, article))


class PlanManageFormViewTests(TestCase):
    """/manage/billing/plans/ create & update — previously untested at the
    view level, which is exactly how grants_premium_newsletter ended up
    referenced in plan_form.html but missing from SubscriptionPlanForm.
    Meta.fields entirely: nothing exercised the real form/view together,
    only the model field directly (see PlanPerkEnforcementTests above).
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            email='plan-form-admin@example.com', password='pw', first_name='A', last_name='D', role=User.Role.ADMIN,
        )

    def test_create_saves_every_perk_field(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('billing:manage_plan_create'), {
            'name': 'Full Plan', 'plan_type': SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            'price': '9.99', 'duration_days': 30, 'description': '',
            'grants_ad_free_reading': 'on', 'grants_unlimited_articles': 'on', 'grants_premium_newsletter': 'on',
            'grants_full_archive': 'on', 'gift_articles_per_month': 3,
        })
        self.assertEqual(response.status_code, 302)
        plan = SubscriptionPlan.objects.get(name='Full Plan')
        self.assertTrue(plan.grants_ad_free_reading)
        self.assertTrue(plan.grants_unlimited_articles)
        self.assertTrue(plan.grants_premium_newsletter)
        self.assertTrue(plan.grants_full_archive)
        self.assertEqual(plan.gift_articles_per_month, 3)

    def test_create_without_checkboxes_saves_all_perks_off(self):
        # Unchecked HTML checkboxes aren't submitted at all — confirms the
        # form correctly reads that as False rather than erroring or
        # defaulting to True.
        self.client.force_login(self.admin)
        self.client.post(reverse('billing:manage_plan_create'), {
            'name': 'Bare Plan', 'plan_type': SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            'price': '9.99', 'duration_days': 30, 'description': '', 'gift_articles_per_month': 0,
        })
        plan = SubscriptionPlan.objects.get(name='Bare Plan')
        self.assertFalse(plan.grants_ad_free_reading)
        self.assertFalse(plan.grants_unlimited_articles)
        self.assertFalse(plan.grants_premium_newsletter)
        self.assertFalse(plan.grants_full_archive)

    def test_update_changes_gift_allowance(self):
        plan = SubscriptionPlan.objects.create(
            name='Editable Plan', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=5, duration_days=30, gift_articles_per_month=0,
        )
        self.client.force_login(self.admin)
        self.client.post(reverse('billing:manage_plan_update', args=[plan.pk]), {
            'name': plan.name, 'plan_type': plan.plan_type, 'price': plan.price, 'duration_days': plan.duration_days,
            'description': '', 'gift_articles_per_month': 5,
        })
        plan.refresh_from_db()
        self.assertEqual(plan.gift_articles_per_month, 5)


class MeteredPaywallTests(TestCase):
    """billing.access.consume_free_sample/free_sample_reads_used — the "N
    free subscription articles a month" allowance for readers without a
    real subscription. Authenticated-reader path only here (no session
    needed); the anonymous/session-based path is covered end-to-end in
    MeteredPaywallViewTests below via the real test Client, which manages a
    real session the way RequestFactory doesn't.
    """

    def setUp(self):
        self.reader = User.objects.create_user(
            email='meter-reader@example.com', password='pw', first_name='M', last_name='R',
        )

    def _request(self):
        request = RequestFactory().get('/')
        request.user = self.reader
        return request

    def test_grants_access_up_to_the_monthly_limit(self):
        request = self._request()
        articles = [
            make_article(Article.AccessType.SUBSCRIPTION, slug_suffix=f'-{n}')
            for n in range(FREE_SAMPLE_LIMIT_PER_MONTH)
        ]
        for article in articles:
            self.assertTrue(consume_free_sample(request, article))

    def test_denies_access_past_the_monthly_limit(self):
        request = self._request()
        for n in range(FREE_SAMPLE_LIMIT_PER_MONTH):
            consume_free_sample(request, make_article(Article.AccessType.SUBSCRIPTION, slug_suffix=f'-{n}'))
        one_too_many = make_article(Article.AccessType.SUBSCRIPTION, slug_suffix='-overflow')
        self.assertFalse(consume_free_sample(request, one_too_many))

    def test_rereading_the_same_article_does_not_consume_a_second_slot(self):
        request = self._request()
        article = make_article(Article.AccessType.SUBSCRIPTION)
        for _ in range(FREE_SAMPLE_LIMIT_PER_MONTH + 2):
            self.assertTrue(consume_free_sample(request, article))
        self.assertEqual(free_sample_reads_used(request), 1)

    def test_pay_per_article_is_never_metered(self):
        request = self._request()
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=2)
        self.assertFalse(consume_free_sample(request, article))

    def test_free_sample_reads_used_counts_distinct_articles(self):
        request = self._request()
        for n in range(3):
            consume_free_sample(request, make_article(Article.AccessType.SUBSCRIPTION, slug_suffix=f'-{n}'))
        self.assertEqual(free_sample_reads_used(request), 3)


class MeteredPaywallViewTests(TestCase):
    """End-to-end via the real article detail page and PDF download — the
    anonymous/session-based counting path RequestFactory can't exercise
    (no session middleware), plus proof the metering is actually wired into
    the view, not just the access.py functions in isolation.
    """

    def _subscription_article(self, n):
        article = make_article(Article.AccessType.SUBSCRIPTION)
        article.slug = f'metered-article-{n}'
        article.html_content = f'Secret text {n}'
        article.save()
        return article

    def test_anonymous_reader_gets_full_text_up_to_the_monthly_limit(self):
        for n in range(FREE_SAMPLE_LIMIT_PER_MONTH):
            article = self._subscription_article(n)
            response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
            self.assertContains(response, f'Secret text {n}')

    def test_anonymous_reader_is_gated_past_the_monthly_limit(self):
        for n in range(FREE_SAMPLE_LIMIT_PER_MONTH):
            article = self._subscription_article(n)
            self.client.get(reverse('articles:article_detail', args=[article.slug]))
        one_too_many = self._subscription_article(FREE_SAMPLE_LIMIT_PER_MONTH)
        response = self.client.get(reverse('articles:article_detail', args=[one_too_many.slug]))
        self.assertNotContains(response, f'Secret text {FREE_SAMPLE_LIMIT_PER_MONTH}')

    def test_free_sample_notice_shown_with_correct_count(self):
        article = self._subscription_article(0)
        response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
        self.assertContains(response, 'of your')
        self.assertContains(response, str(FREE_SAMPLE_LIMIT_PER_MONTH))

    def test_revisiting_the_same_article_does_not_use_a_second_slot(self):
        article = self._subscription_article(0)
        url = reverse('articles:article_detail', args=[article.slug])
        for _ in range(FREE_SAMPLE_LIMIT_PER_MONTH + 2):
            response = self.client.get(url)
            self.assertContains(response, 'Secret text 0')

    def test_pdf_download_works_for_a_free_sample_grant(self):
        article = self._subscription_article(0)
        article.pdf_file = 'articles/2026/09/test.pdf'
        article.save()
        self.client.get(reverse('articles:article_detail', args=[article.slug]))  # consumes the free sample
        response = self.client.get(reverse('articles:article_download', args=[article.slug]))
        self.assertEqual(response.status_code, 302)  # redirects to the file — see article_download

    def test_subscriber_is_never_metered(self):
        reader = User.objects.create_user(email='unmetered@example.com', password='pw', first_name='U', last_name='M')
        plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=5, duration_days=30,
        )
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=reader, plan=plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.client.force_login(reader)
        for n in range(FREE_SAMPLE_LIMIT_PER_MONTH + 3):
            article = self._subscription_article(n)
            response = self.client.get(reverse('articles:article_detail', args=[article.slug]))
            self.assertContains(response, f'Secret text {n}')
            self.assertNotContains(response, 'of your')  # no free-sample notice — real access, not metered


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


class SelfServeCheckoutTests(TestCase):
    """Public checkout — no gateway is wired in yet (StubGateway always
    succeeds, see billing/gateway.py), but the flow itself is real and
    self-serve: a reader completes it without any editorial action.
    """

    def setUp(self):
        self.reader = User.objects.create_user(
            email='checkout@example.com', password='pw', first_name='C', last_name='O',
        )
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
            price=5, duration_days=30,
        )

    def test_plan_browse_is_public(self):
        response = self.client.get(reverse('billing:plan_browse'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.plan.name)

    def test_subscribe_checkout_requires_login(self):
        response = self.client.get(reverse('billing:subscribe_checkout', args=[self.plan.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_subscribe_checkout_creates_active_subscription(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('billing:subscribe_checkout', args=[self.plan.pk]))
        self.assertEqual(response.status_code, 302)
        subscription = UserSubscription.objects.get(user=self.reader, plan=self.plan)
        self.assertTrue(subscription.is_currently_active)
        self.assertTrue(subscription.payment_reference.startswith('stub-'))

    def test_already_subscribed_reader_is_not_double_charged(self):
        today = timezone.localdate()
        UserSubscription.objects.create(
            user=self.reader, plan=self.plan, start_date=today, end_date=today + datetime.timedelta(days=30),
        )
        self.client.force_login(self.reader)
        response = self.client.post(reverse('billing:subscribe_checkout', args=[self.plan.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserSubscription.objects.filter(user=self.reader).count(), 1)

    def test_purchase_checkout_creates_purchase_and_unlocks_article(self):
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=3)
        self.client.force_login(self.reader)
        response = self.client.post(reverse('billing:purchase_checkout', args=[article.slug]))
        self.assertEqual(response.status_code, 302)
        purchase = ArticlePurchase.objects.get(user=self.reader, article=article)
        self.assertTrue(purchase.payment_reference.startswith('stub-'))
        self.assertTrue(article_is_accessible(self.reader, article))

    def test_declined_subscribe_charge_shows_error_and_creates_nothing(self):
        # Fault injection: StubGateway always succeeds today, so this branch
        # (billing/views.py's `if result.success: ... ; messages.error(...)`
        # else-path) is currently unreachable in production and has never
        # actually run — worth confirming it behaves correctly before a
        # real gateway starts returning real declines.
        self.client.force_login(self.reader)
        with patch('billing.gateway.get_gateway') as mock_get_gateway:
            mock_get_gateway.return_value.charge.return_value = PaymentResult(
                success=False, reference='', error='Card declined',
            )
            response = self.client.post(reverse('billing:subscribe_checkout', args=[self.plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Card declined')
        self.assertFalse(UserSubscription.objects.filter(user=self.reader).exists())

    def test_gateway_exception_on_subscribe_is_treated_as_a_decline(self):
        # Fault injection: a real gateway integration is a network call and
        # can raise (timeout, connection reset, provider outage) rather
        # than cleanly returning success=False. charge_safely()
        # (billing/gateway.py) catches that and converts it into the exact
        # same declined-payment path — no 500, no subscription created.
        self.client.force_login(self.reader)
        with patch('billing.gateway.get_gateway') as mock_get_gateway:
            mock_get_gateway.return_value.charge.side_effect = ConnectionError('Gateway unreachable')
            response = self.client.post(reverse('billing:subscribe_checkout', args=[self.plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment failed')
        self.assertFalse(UserSubscription.objects.filter(user=self.reader).exists())

    def test_declined_purchase_charge_shows_error_and_creates_nothing(self):
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=3)
        self.client.force_login(self.reader)
        with patch('billing.gateway.get_gateway') as mock_get_gateway:
            mock_get_gateway.return_value.charge.return_value = PaymentResult(
                success=False, reference='', error='Card declined',
            )
            response = self.client.post(reverse('billing:purchase_checkout', args=[article.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Card declined')
        self.assertFalse(ArticlePurchase.objects.filter(user=self.reader, article=article).exists())
        self.assertFalse(article_is_accessible(self.reader, article))

    def test_gateway_exception_on_purchase_is_treated_as_a_decline(self):
        article = make_article(Article.AccessType.PAY_PER_ARTICLE, price=3)
        self.client.force_login(self.reader)
        with patch('billing.gateway.get_gateway') as mock_get_gateway:
            mock_get_gateway.return_value.charge.side_effect = ConnectionError('Gateway unreachable')
            response = self.client.post(reverse('billing:purchase_checkout', args=[article.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment failed')
        self.assertFalse(ArticlePurchase.objects.filter(user=self.reader, article=article).exists())


class PlanDetailAndComparisonTests(TestCase):
    def setUp(self):
        f1 = PlanFeature.objects.create(label='Full access to subscriber-only articles', order=0)
        f2 = PlanFeature.objects.create(label='Priority support', order=1)
        f3 = PlanFeature.objects.create(label='Dedicated account manager', order=2)
        self.basic = SubscriptionPlan.objects.create(
            name='Basic', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=100, duration_days=30,
        )
        self.basic.features.set([f1])
        self.premium = SubscriptionPlan.objects.create(
            name='Premium', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_ANNUAL, price=1000, duration_days=365,
            is_featured=True,
        )
        self.premium.features.set([f1, f2])
        self.enterprise = SubscriptionPlan.objects.create(
            name='Enterprise', plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL, price=5000, duration_days=365,
        )
        self.enterprise.features.set([f1, f2, f3])

    def test_comparison_matrix_shape_and_ordering(self):
        plans = [self.basic, self.premium, self.enterprise]
        matrix = build_comparison_matrix(plans)
        self.assertEqual([row['feature'].label for row in matrix], [
            'Full access to subscriber-only articles', 'Priority support', 'Dedicated account manager',
        ])
        # Basic has only the first feature; Enterprise has all three.
        self.assertEqual([row['included'][0] for row in matrix], [True, False, False])
        self.assertEqual([row['included'][2] for row in matrix], [True, True, True])

    def test_plan_detail_page_renders_its_own_features_and_comparison_table(self):
        response = self.client.get(reverse('billing:plan_detail', args=[self.premium.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Premium')
        self.assertContains(response, 'Priority support')
        self.assertContains(response, 'MOST POPULAR')
        # Comparison table includes the other plans too.
        self.assertContains(response, 'Basic')
        self.assertContains(response, 'Enterprise')

    def test_inactive_plan_detail_page_404s(self):
        self.basic.is_active = False
        self.basic.save(update_fields=['is_active'])
        response = self.client.get(reverse('billing:plan_detail', args=[self.basic.pk]))
        self.assertEqual(response.status_code, 404)


class PlanListFilterTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='plan-filter-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)
        self.monthly = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=10, duration_days=30,
        )
        self.annual = SubscriptionPlan.objects.create(
            name='Annual', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_ANNUAL, price=100, duration_days=365,
            is_active=False,
        )

    def test_filters_by_plan_type(self):
        response = self.client.get(reverse('billing:manage_plan_list'), {'plan_type': SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY})
        self.assertEqual(list(response.context['plans']), [self.monthly])

    def test_filters_by_active_status(self):
        response = self.client.get(reverse('billing:manage_plan_list'), {'active': 'no'})
        self.assertEqual(list(response.context['plans']), [self.annual])

    def test_default_ordering_is_newest_first(self):
        # Distinct from PlanBrowseView (public), which orders by price on
        # purpose — this is the editorial manage list.
        response = self.client.get(reverse('billing:manage_plan_list'))
        plans = list(response.context['plans'])
        self.assertLess(plans.index(self.annual), plans.index(self.monthly))


class SubscriptionListFilterTests(TestCase):
    def setUp(self):
        self.eic = User.objects.create_user(
            email='sub-filter-eic@example.com', password='pw', first_name='E', last_name='C', role=User.Role.EDITOR_IN_CHIEF,
        )
        self.client.force_login(self.eic)
        self.reader = User.objects.create_user(email='sub-filter-reader@example.com', password='pw', first_name='R', last_name='D')
        self.monthly = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=10, duration_days=30,
        )
        self.annual = SubscriptionPlan.objects.create(
            name='Annual', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_ANNUAL, price=100, duration_days=365,
        )
        self.active_sub = UserSubscription.objects.create(
            user=self.reader, plan=self.monthly, status=UserSubscription.Status.ACTIVE,
            start_date=timezone.localdate(), end_date=timezone.localdate() + datetime.timedelta(days=10),
        )
        self.cancelled_sub = UserSubscription.objects.create(
            user=self.reader, plan=self.annual, status=UserSubscription.Status.CANCELLED,
            start_date=timezone.localdate(), end_date=timezone.localdate() + datetime.timedelta(days=10),
        )

    def test_filters_by_status(self):
        response = self.client.get(reverse('billing:manage_subscription_list'), {'status': UserSubscription.Status.CANCELLED})
        self.assertEqual(list(response.context['subscriptions']), [self.cancelled_sub])

    def test_filters_by_plan(self):
        response = self.client.get(reverse('billing:manage_subscription_list'), {'plan': self.monthly.pk})
        self.assertEqual(list(response.context['subscriptions']), [self.active_sub])


class SubscriptionExpiringSoonTests(TestCase):
    def setUp(self):
        self.eic = User.objects.create_user(
            email='sub-expiring-eic@example.com', password='pw', first_name='E', last_name='C', role=User.Role.EDITOR_IN_CHIEF,
        )
        self.client.force_login(self.eic)
        self.reader = User.objects.create_user(email='sub-expiring-reader@example.com', password='pw', first_name='R', last_name='D')
        self.plan = SubscriptionPlan.objects.create(
            name='Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY, price=10, duration_days=30,
        )
        self.expiring_soon = UserSubscription.objects.create(
            user=self.reader, plan=self.plan, status=UserSubscription.Status.ACTIVE,
            start_date=timezone.localdate() - datetime.timedelta(days=27), end_date=timezone.localdate() + datetime.timedelta(days=3),
        )
        self.not_expiring_soon = UserSubscription.objects.create(
            user=self.reader, plan=self.plan, status=UserSubscription.Status.ACTIVE,
            start_date=timezone.localdate(), end_date=timezone.localdate() + datetime.timedelta(days=30),
        )

    def test_expiring_filter_shows_only_soon_to_expire_active_subscriptions(self):
        response = self.client.get(reverse('billing:manage_subscription_list'), {'expiring': '1'})
        self.assertEqual(list(response.context['subscriptions']), [self.expiring_soon])

    def test_no_filter_shows_all(self):
        response = self.client.get(reverse('billing:manage_subscription_list'))
        self.assertEqual(set(response.context['subscriptions']), {self.expiring_soon, self.not_expiring_soon})

    def test_expiring_badge_shown_on_the_list_page(self):
        response = self.client.get(reverse('billing:manage_subscription_list'))
        self.assertContains(response, 'Expiring soon')

    def test_dashboard_shows_expiring_soon_count(self):
        response = self.client.get(reverse('admin_custom:dashboard'))
        self.assertEqual(response.context['expiring_soon_subscriptions'], 1)
        self.assertContains(response, '1 expiring within 7 days')


class PurchaseListFilterTests(TestCase):
    def setUp(self):
        self.eic = User.objects.create_user(
            email='purchase-filter-eic@example.com', password='pw', first_name='E', last_name='C', role=User.Role.EDITOR_IN_CHIEF,
        )
        self.client.force_login(self.eic)
        self.reader = User.objects.create_user(email='purchase-filter-reader@example.com', password='pw', first_name='R', last_name='D')
        self.article_a = make_article(Article.AccessType.PAY_PER_ARTICLE, price=5)
        self.article_b = Article.objects.create(
            title='Other Article', slug='other-article', abstract='Abstract',
            article_type=Article.ArticleType.NEWS_COMMENTARY,
            access_type=Article.AccessType.PAY_PER_ARTICLE, price=7, status=Article.Status.PUBLISHED,
        )
        self.purchase_a = ArticlePurchase.objects.create(user=self.reader, article=self.article_a, amount=5)
        self.purchase_b = ArticlePurchase.objects.create(user=self.reader, article=self.article_b, amount=7)

    def test_filters_by_article(self):
        response = self.client.get(reverse('billing:manage_purchase_list'), {'article': self.article_b.pk})
        self.assertEqual(list(response.context['purchases']), [self.purchase_b])

    def test_no_filter_shows_all_purchases(self):
        response = self.client.get(reverse('billing:manage_purchase_list'))
        self.assertEqual(set(response.context['purchases']), {self.purchase_a, self.purchase_b})

    def test_article_dropdown_only_lists_articles_with_purchases(self):
        make_article(Article.AccessType.OPEN_ACCESS)
        response = self.client.get(reverse('billing:manage_purchase_list'))
        self.assertEqual(set(response.context['articles']), {self.article_a, self.article_b})
