import csv
import datetime
from decimal import Decimal

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import ListView, TemplateView
from django_comments_xtd.models import XtdComment

from ads.models import AdEvent, AdSlot
from articles.models import Article, ArticleView
from billing.models import ArticlePurchase, SubscriptionPlan, UserSubscription
from newsletter.models import NewsletterIssue, Subscriber
from pitches.models import StoryPitch
from training.models import Enrollment, TrainingCourse
from users.decorators import role_required
from users.models import User

# Single source of truth is User.EDITORIAL_ROLES (see users/models.py).
EDITORIAL_ROLES = User.EDITORIAL_ROLES

# Palette for donut charts — chosen for contrast against white cards and
# against each other; order doesn't matter, slices are assigned by
# descending count so the biggest slice always gets the first color.
TYPE_CHART_COLORS = ['#7c6fea', '#34d399', '#fbbf24', '#60a5fa', '#f87171', '#22d3ee', '#f472b6', '#a3a3a3']

# Revenue events (enrollments, subscriptions, purchases) are much sparser
# than page views — a 14-day window (AnalyticsView.TREND_DAYS) would show
# mostly zeros for a smaller site. 30 days is the more standard window for
# financial reporting anyway.
REVENUE_TREND_DAYS = 30


def _daily_counts(queryset, date_field, days):
    """Buckets `queryset` row counts into local-midnight-to-midnight ranges
    for each day in `days`. Explicit datetime ranges rather than a
    `date_field__date=day` lookup — the latter needs MySQL's CONVERT_TZ() to
    resolve the named TIME_ZONE, which silently matches nothing unless the
    server's mysql.time_zone_name tables have been loaded (see
    DashboardHomeView.get_context_data above for the same reasoning).
    """
    counts = []
    for day in days:
        day_start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
        day_end = day_start + datetime.timedelta(days=1)
        counts.append(queryset.filter(**{f'{date_field}__gte': day_start, f'{date_field}__lt': day_end}).count())
    return counts


def _daily_sums(queryset, date_field, sum_field, days):
    """Same day-bucketing as _daily_counts, but Sum(sum_field) per day
    instead of a row count — used for revenue trends (RevenueTrainingView/
    RevenueSubscriptionsView/RevenueOverviewView below).
    """
    sums = []
    for day in days:
        day_start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
        day_end = day_start + datetime.timedelta(days=1)
        total = queryset.filter(
            **{f'{date_field}__gte': day_start, f'{date_field}__lt': day_end},
        ).aggregate(total=Sum(sum_field))['total'] or 0
        sums.append(total)
    return sums


def _trend_bars(day_labels, counts):
    max_count = max(counts + [1])
    return [
        {'label': label, 'count': count, 'pct': round(count / max_count * 100)}
        for label, count in zip(day_labels, counts)
    ]


def _donut_breakdown(counts_by_value, choices):
    """Same "sorted slices + conic-gradient stops" shape as DashboardHomeView's
    Articles-by-Type donut, factored out here since AnalyticsView needs it twice
    (subscription plan mix, newsletter subscriber status).
    """
    rows = [{'label': label, 'count': counts_by_value.get(value, 0)} for value, label in choices if counts_by_value.get(value)]
    rows.sort(key=lambda d: -d['count'])
    total = sum(d['count'] for d in rows)
    gradient_stops = []
    cursor = 0
    for i, d in enumerate(rows):
        d['color'] = TYPE_CHART_COLORS[i % len(TYPE_CHART_COLORS)]
        d['pct'] = round(d['count'] / total * 100) if total else 0
        start = cursor
        cursor = 100 if i == len(rows) - 1 else cursor + d['pct']
        gradient_stops.append(f"{d['color']} {start}% {cursor}%")
    gradient = ', '.join(gradient_stops) if gradient_stops else '#e5e7eb 0% 100%'
    return rows, gradient, total


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class DashboardHomeView(TemplateView):
    """Editorial Command Center — KPIs and activity charts for the news site
    + editorial workspace (see CLAUDE.md SCOPE NOTE). Deliberately has no
    submission/peer-review metrics — those apps were removed post-OJS-pivot.
    """

    template_name = 'admin_custom/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # localdate(), not now().date() — TIME_ZONE is Asia/Kathmandu (UTC+5:45),
        # so a plain UTC "now" can already be tomorrow in local time near midnight.
        today = timezone.localdate()

        # -- KPI row -----------------------------------------------------
        article_status_counts = dict(
            Article.objects.values_list('status').annotate(count=Count('id')).order_by(),
        )
        context['published_count'] = article_status_counts.get(Article.Status.PUBLISHED, 0)
        context['draft_count'] = article_status_counts.get(Article.Status.DRAFT, 0)

        this_month_start = today.replace(day=1)
        last_month_end = this_month_start - datetime.timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        published_this_month = Article.objects.filter(
            status=Article.Status.PUBLISHED, publication_date__gte=this_month_start, publication_date__lte=today,
        ).count()
        published_last_month = Article.objects.filter(
            status=Article.Status.PUBLISHED, publication_date__gte=last_month_start, publication_date__lte=last_month_end,
        ).count()
        context['published_this_month'] = published_this_month
        # None (not 0) when there's no baseline — a "vs last month" percentage
        # from a zero baseline is meaningless, so the template shows no pill instead.
        context['published_delta_pct'] = (
            round((published_this_month - published_last_month) / published_last_month * 100)
            if published_last_month else None
        )

        context['pending_verifications'] = User.objects.filter(
            verification_status=User.VerificationStatus.PENDING,
        ).count()

        enrollment_counts = dict(
            Enrollment.objects.values_list('status').annotate(count=Count('id')).order_by(),
        )
        context['active_enrollments'] = enrollment_counts.get(Enrollment.Status.ACTIVE, 0)
        context['active_course_count'] = TrainingCourse.objects.filter(is_active=True).count()

        context['active_subscriptions'] = UserSubscription.objects.filter(
            status=UserSubscription.Status.ACTIVE, start_date__lte=today, end_date__gte=today,
        ).count()
        # No renewal-nudge workflow exists yet — this is just the first,
        # proactive surface for it (see billing/views.py's matching
        # EXPIRING_SOON_WINDOW_DAYS filter on the subscriptions manage list).
        context['expiring_soon_subscriptions'] = UserSubscription.objects.filter(
            status=UserSubscription.Status.ACTIVE,
            end_date__gte=today, end_date__lte=today + datetime.timedelta(days=7),
        ).count()
        context['newsletter_subscribers'] = Subscriber.objects.filter(status=Subscriber.Status.CONFIRMED).count()
        context['open_pitches'] = StoryPitch.objects.filter(
            status__in=[StoryPitch.Status.SUBMITTED, StoryPitch.Status.IN_REVIEW],
        ).count()

        # -- "Articles Created vs Published" bar chart, last 7 days -------
        days = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]
        daily_stats = []
        for day in days:
            # Explicit local-midnight-to-local-midnight range instead of a
            # `created_at__date=day` lookup — the latter needs MySQL's
            # CONVERT_TZ() to resolve the named TIME_ZONE, which silently
            # returns NULL (matching nothing, ever) unless the server's
            # mysql.time_zone_name tables have been loaded via
            # mysql_tzinfo_to_sql. A plain datetime range doesn't need that.
            day_start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
            day_end = day_start + datetime.timedelta(days=1)
            created = Article.objects.filter(created_at__gte=day_start, created_at__lt=day_end).count()
            published = Article.objects.filter(publication_date=day).count()
            daily_stats.append({'label': day.strftime('%b %-d'), 'created': created, 'published': published})
        max_daily = max([max(d['created'], d['published']) for d in daily_stats] + [1])
        for d in daily_stats:
            d['created_pct'] = round(d['created'] / max_daily * 100)
            d['published_pct'] = round(d['published'] / max_daily * 100)
        context['daily_stats'] = daily_stats
        context['daily_created_total'] = sum(d['created'] for d in daily_stats)
        context['daily_published_total'] = sum(d['published'] for d in daily_stats)

        # -- "Articles by Type" donut --------------------------------------
        type_counts = dict(
            Article.objects.values_list('article_type').annotate(count=Count('id')).order_by(),
        )
        articles_by_type = [
            {'label': label, 'count': type_counts[value]}
            for value, label in Article.ArticleType.choices if type_counts.get(value)
        ]
        articles_by_type.sort(key=lambda d: -d['count'])
        type_total = sum(d['count'] for d in articles_by_type)
        gradient_stops = []
        cursor = 0
        for i, d in enumerate(articles_by_type):
            d['color'] = TYPE_CHART_COLORS[i % len(TYPE_CHART_COLORS)]
            d['pct'] = round(d['count'] / type_total * 100) if type_total else 0
            start = cursor
            cursor = 100 if i == len(articles_by_type) - 1 else cursor + d['pct']
            gradient_stops.append(f"{d['color']} {start}% {cursor}%")
        context['articles_by_type'] = articles_by_type
        context['articles_by_type_gradient'] = ', '.join(gradient_stops) if gradient_stops else '#e5e7eb 0% 100%'
        context['article_type_total'] = type_total

        # -- Verification breakdown ----------------------------------------
        verification_counts = dict(
            User.objects.values_list('verification_status').annotate(count=Count('id')).order_by(),
        )
        verification_total = User.objects.count()
        verification_display = [
            (User.VerificationStatus.APPROVED, 'Approved', 'bg-green-500'),
            (User.VerificationStatus.PENDING, 'Pending', 'bg-amber-400'),
            (User.VerificationStatus.REJECTED, 'Rejected', 'bg-red-500'),
        ]
        context['verification_breakdown'] = [
            {
                'label': label, 'bar_color': bar_color,
                'count': verification_counts.get(value, 0),
                'pct': round(verification_counts.get(value, 0) / verification_total * 100) if verification_total else 0,
            }
            for value, label, bar_color in verification_display
        ]
        context['verification_total'] = verification_total

        # -- Training enrollment breakdown ----------------------------------
        enrollment_total = sum(enrollment_counts.values())
        enrollment_display = [
            (Enrollment.Status.ACTIVE, 'Active', '#34d399'),
            (Enrollment.Status.COMPLETED, 'Completed', '#60a5fa'),
            (Enrollment.Status.CANCELLED, 'Cancelled', '#d1d5db'),
        ]
        context['training_breakdown'] = [
            {
                'label': label, 'color': color,
                'count': enrollment_counts.get(value, 0),
                'pct': round(enrollment_counts.get(value, 0) / enrollment_total * 100) if enrollment_total else 0,
            }
            for value, label, color in enrollment_display
        ]
        context['enrollment_total'] = enrollment_total

        context['recent_articles'] = Article.objects.select_related('issue').order_by('-updated_at')[:5]

        return context


def _training_revenue_trend(days, day_labels):
    """Daily 'collected' revenue (PAID enrollments, priced at course.price,
    bucketed by enrolled_at) — used by both RevenueTrainingView and
    RevenueOverviewView, which is why it's a standalone function rather than
    inlined in one view's get_context_data.
    """
    paid_enrollments = Enrollment.objects.filter(payment_status=Enrollment.PaymentStatus.PAID)
    sums = _daily_sums(paid_enrollments, 'enrolled_at', 'course__price', days)
    return _trend_bars(day_labels, sums), sums


def _subscription_purchase_revenue_trend(days, day_labels):
    """Daily subscription + purchase revenue, used by both
    RevenueSubscriptionsView and RevenueOverviewView. Subscription revenue
    here is the plan price at the moment a subscription is *created*
    (bucketed by created_at) — a proxy for the initial payment, not a full
    ledger of recurring renewals, since UserSubscription only tracks the
    current period rather than a payment history (see its docstring —
    renewals will need a real gateway's webhook events to track properly).
    Purchase revenue is exact: ArticlePurchase.amount is a real one-time
    transaction, bucketed by purchased_at.
    """
    sub_sums = _daily_sums(UserSubscription.objects.all(), 'created_at', 'plan__price', days)
    purchase_sums = _daily_sums(ArticlePurchase.objects.all(), 'purchased_at', 'amount', days)
    combined = [s + p for s, p in zip(sub_sums, purchase_sums)]
    return _trend_bars(day_labels, combined), combined


def _mrr_estimate(active_subs):
    """Approximate monthly-recurring-revenue value of currently active
    subscriptions — normalizes each plan's price to a 30-day cycle (e.g. an
    annual plan counts at 1/12th its price) so mixed monthly/annual/
    institutional plans combine into one comparable number. Shared by
    AnalyticsView and RevenueSubscriptionsView/RevenueOverviewView below.
    """
    if not active_subs:
        return Decimal('0')
    return round(
        sum((sub.plan.price / (Decimal(sub.plan.duration_days) / Decimal(30))) for sub in active_subs), 2,
    )


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class RevenueTrainingView(TemplateView):
    """Training course revenue only, from Enrollment.payment_status — see
    RevenueOverviewView for the combined picture across training,
    subscriptions, and article purchases, and RevenueSubscriptionsView for
    the subscription/purchase side specifically.
    """

    template_name = 'admin_custom/revenue_training.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        def total_for(payment_status):
            return Enrollment.objects.filter(
                payment_status=payment_status,
            ).aggregate(total=Sum('course__price'))['total'] or 0

        context['collected_total'] = total_for(Enrollment.PaymentStatus.PAID)
        context['pending_total'] = total_for(Enrollment.PaymentStatus.PENDING)
        context['refunded_total'] = total_for(Enrollment.PaymentStatus.REFUNDED)
        context['enrollment_total'] = Enrollment.objects.count()

        today = timezone.localdate()
        days = [today - datetime.timedelta(days=i) for i in range(REVENUE_TREND_DAYS - 1, -1, -1)]
        day_labels = [d.strftime('%b %-d') for d in days]
        context['revenue_trend'], _ = _training_revenue_trend(days, day_labels)

        courses = TrainingCourse.objects.annotate(
            paid_count=Count('enrollments', filter=Q(enrollments__payment_status=Enrollment.PaymentStatus.PAID)),
            pending_count=Count('enrollments', filter=Q(enrollments__payment_status=Enrollment.PaymentStatus.PENDING)),
            refunded_count=Count('enrollments', filter=Q(enrollments__payment_status=Enrollment.PaymentStatus.REFUNDED)),
            total_enrollments=Count('enrollments'),
        ).order_by('-total_enrollments')
        for course in courses:
            course.collected = course.paid_count * course.price
        context['courses'] = courses

        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class RevenueSubscriptionsView(TemplateView):
    """Subscription + article-purchase revenue — the billing-app side of
    the picture RevenueTrainingView doesn't cover. See RevenueOverviewView
    for training and subscriptions combined into one summary.
    """

    template_name = 'admin_custom/revenue_subscriptions.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()

        active_subs = list(
            UserSubscription.objects.filter(
                status=UserSubscription.Status.ACTIVE, start_date__lte=today, end_date__gte=today,
            ).select_related('plan'),
        )
        context['active_subscription_count'] = len(active_subs)
        context['mrr_estimate'] = _mrr_estimate(active_subs)
        context['cancelled_subscription_count'] = UserSubscription.objects.filter(
            status=UserSubscription.Status.CANCELLED,
        ).count()

        # Per-plan breakdown — active count (current) and lifetime revenue
        # (every subscription ever created on this plan × its price, a
        # proxy for total realized payments — see _subscription_purchase_
        # revenue_trend's docstring on why this isn't a full renewal ledger).
        plans = SubscriptionPlan.objects.annotate(
            active_count=Count('subscriptions', filter=Q(
                subscriptions__status=UserSubscription.Status.ACTIVE,
                subscriptions__start_date__lte=today, subscriptions__end_date__gte=today,
            )),
            lifetime_count=Count('subscriptions'),
        ).order_by('-lifetime_count')
        for plan in plans:
            plan.lifetime_revenue = plan.lifetime_count * plan.price
        context['plans'] = plans

        context['purchase_count'] = ArticlePurchase.objects.count()
        context['purchase_revenue'] = ArticlePurchase.objects.aggregate(total=Sum('amount'))['total'] or 0

        days = [today - datetime.timedelta(days=i) for i in range(REVENUE_TREND_DAYS - 1, -1, -1)]
        day_labels = [d.strftime('%b %-d') for d in days]
        context['revenue_trend'], _ = _subscription_purchase_revenue_trend(days, day_labels)

        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class RevenueOverviewView(TemplateView):
    """Combined revenue across training, subscriptions, and article
    purchases — one headline number and trend, with drill-down links to
    RevenueTrainingView and RevenueSubscriptionsView for the detail. MRR is
    shown separately, not folded into "Total Revenue": it's a forward-
    looking projection from currently active subscriptions, not money
    actually collected, so combining it with the other (realized) totals
    would overstate the number.
    """

    template_name = 'admin_custom/revenue_overview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()

        training_total = Enrollment.objects.filter(
            payment_status=Enrollment.PaymentStatus.PAID,
        ).aggregate(total=Sum('course__price'))['total'] or 0
        subscription_total = UserSubscription.objects.aggregate(
            total=Sum('plan__price'),
        )['total'] or 0
        purchase_total = ArticlePurchase.objects.aggregate(total=Sum('amount'))['total'] or 0

        context['training_total'] = training_total
        context['subscription_total'] = subscription_total
        context['purchase_total'] = purchase_total
        context['total_revenue'] = training_total + subscription_total + purchase_total

        active_subs = list(
            UserSubscription.objects.filter(
                status=UserSubscription.Status.ACTIVE, start_date__lte=today, end_date__gte=today,
            ).select_related('plan'),
        )
        context['mrr_estimate'] = _mrr_estimate(active_subs)

        days = [today - datetime.timedelta(days=i) for i in range(REVENUE_TREND_DAYS - 1, -1, -1)]
        day_labels = [d.strftime('%b %-d') for d in days]
        _, training_sums = _training_revenue_trend(days, day_labels)
        _, sub_purchase_sums = _subscription_purchase_revenue_trend(days, day_labels)
        combined_sums = [t + s for t, s in zip(training_sums, sub_purchase_sums)]
        context['revenue_trend'] = _trend_bars(day_labels, combined_sums)

        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AnalyticsView(TemplateView):
    """Cross-domain BI overview: article readership, subscription/purchase
    revenue, ad performance, and newsletter growth in one place — a level
    above DashboardHomeView's day-to-day KPIs (today's counts) and
    RevenueOverviewView's revenue-specific detail pages. Read-only in the browser; see
    analytics_csv_export below for the downloadable version.
    """

    template_name = 'admin_custom/analytics.html'
    TREND_DAYS = 14

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        days = [today - datetime.timedelta(days=i) for i in range(self.TREND_DAYS - 1, -1, -1)]
        day_labels = [d.strftime('%b %-d') for d in days]
        window_start = timezone.make_aware(datetime.datetime.combine(days[0], datetime.time.min))

        # -- Articles --------------------------------------------------------
        views_counts = _daily_counts(ArticleView.objects.all(), 'viewed_at', days)
        context['article_views_trend'] = _trend_bars(day_labels, views_counts)
        context['article_views_window_total'] = sum(views_counts)

        top_articles = list(
            Article.objects.filter(status=Article.Status.PUBLISHED)
            .annotate(recent_views=Count('page_views', filter=Q(page_views__viewed_at__gte=window_start)))
            .order_by('-recent_views', '-download_count', '-citation_count')[:10],
        )
        context['top_articles'] = [
            a for a in top_articles if a.recent_views or a.download_count or a.citation_count
        ]
        context['lifetime_downloads'] = Article.objects.aggregate(total=Sum('download_count'))['total'] or 0
        context['lifetime_citations'] = Article.objects.aggregate(total=Sum('citation_count'))['total'] or 0

        # -- Subscriptions / revenue ------------------------------------------
        active_subs = list(
            UserSubscription.objects.filter(
                status=UserSubscription.Status.ACTIVE, start_date__lte=today, end_date__gte=today,
            ).select_related('plan'),
        )
        plan_type_counts = {}
        for sub in active_subs:
            plan_type_counts[sub.plan.plan_type] = plan_type_counts.get(sub.plan.plan_type, 0) + 1
        subscription_breakdown, subscription_gradient, active_subscription_count = _donut_breakdown(
            plan_type_counts, SubscriptionPlan.PlanType.choices,
        )
        context['subscription_breakdown'] = subscription_breakdown
        context['subscription_gradient'] = subscription_gradient
        context['active_subscription_count'] = active_subscription_count
        context['mrr_estimate'] = _mrr_estimate(active_subs)

        new_subs_counts = _daily_counts(UserSubscription.objects.all(), 'created_at', days)
        context['new_subscriptions_trend'] = _trend_bars(day_labels, new_subs_counts)
        context['cancelled_subscription_count'] = UserSubscription.objects.filter(
            status=UserSubscription.Status.CANCELLED,
        ).count()
        context['purchase_count'] = ArticlePurchase.objects.count()
        context['purchase_revenue'] = ArticlePurchase.objects.aggregate(total=Sum('amount'))['total'] or 0

        # -- Ads ---------------------------------------------------------------
        ads_all_time_impressions = AdSlot.objects.aggregate(total=Sum('impression_count'))['total'] or 0
        ads_all_time_clicks = AdSlot.objects.aggregate(total=Sum('click_count'))['total'] or 0
        context['ads_all_time_impressions'] = ads_all_time_impressions
        context['ads_all_time_clicks'] = ads_all_time_clicks
        context['ads_all_time_ctr'] = (
            round(ads_all_time_clicks / ads_all_time_impressions * 100, 2) if ads_all_time_impressions else None
        )

        recent_ad_events = AdEvent.objects.filter(occurred_at__gte=window_start)
        context['ads_window_impressions'] = recent_ad_events.filter(event_type=AdEvent.EventType.IMPRESSION).count()
        context['ads_window_clicks'] = recent_ad_events.filter(event_type=AdEvent.EventType.CLICK).count()
        context['top_ads'] = list(AdSlot.objects.order_by('-click_count', '-impression_count')[:5])

        # -- Newsletter / other --------------------------------------------
        subscriber_counts = dict(Subscriber.objects.values_list('status').annotate(count=Count('id')).order_by())
        newsletter_breakdown, newsletter_gradient, newsletter_total = _donut_breakdown(
            subscriber_counts, Subscriber.Status.choices,
        )
        context['newsletter_breakdown'] = newsletter_breakdown
        context['newsletter_gradient'] = newsletter_gradient
        context['newsletter_total'] = newsletter_total
        context['newsletter_confirmed_count'] = subscriber_counts.get(Subscriber.Status.CONFIRMED, 0)

        new_confirmed_counts = _daily_counts(
            Subscriber.objects.filter(status=Subscriber.Status.CONFIRMED), 'confirmed_at', days,
        )
        context['newsletter_confirmed_trend'] = _trend_bars(day_labels, new_confirmed_counts)
        context['newsletter_issues_sent'] = NewsletterIssue.objects.filter(sent_at__isnull=False).count()
        context['newsletter_total_recipients'] = (
            NewsletterIssue.objects.aggregate(total=Sum('recipient_count'))['total'] or 0
        )

        context['open_pitches'] = StoryPitch.objects.filter(
            status__in=[StoryPitch.Status.SUBMITTED, StoryPitch.Status.IN_REVIEW],
        ).count()

        return context


@role_required(*EDITORIAL_ROLES)
def analytics_csv_export(request):
    """CSV export of the /editorial/analytics/ page's numbers — same
    underlying queries as AnalyticsView, reshaped as plain rows instead of
    chart-ready structures (trend bars, donut gradients). One combined file
    with a section per table, matching how the page itself presents
    everything as one dashboard rather than several separate ones.
    """
    today = timezone.localdate()
    days = [today - datetime.timedelta(days=i) for i in range(AnalyticsView.TREND_DAYS - 1, -1, -1)]
    window_start = timezone.make_aware(datetime.datetime.combine(days[0], datetime.time.min))

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="analytics-{today.isoformat()}.csv"'
    writer = csv.writer(response)

    # -- Articles ----------------------------------------------------------
    writer.writerow([f'Article Views (last {AnalyticsView.TREND_DAYS} days)'])
    writer.writerow(['Date', 'Views'])
    views_counts = _daily_counts(ArticleView.objects.all(), 'viewed_at', days)
    for day, count in zip(days, views_counts):
        writer.writerow([day.isoformat(), count])
    writer.writerow([])

    writer.writerow([f'Top Articles (by views in the last {AnalyticsView.TREND_DAYS} days)'])
    writer.writerow(['Title', 'Recent Views', 'Lifetime Downloads', 'Lifetime Citations'])
    top_articles = (
        Article.objects.filter(status=Article.Status.PUBLISHED)
        .annotate(recent_views=Count('page_views', filter=Q(page_views__viewed_at__gte=window_start)))
        .order_by('-recent_views', '-download_count', '-citation_count')[:10]
    )
    for article in top_articles:
        writer.writerow([article.title, article.recent_views, article.download_count, article.citation_count])
    writer.writerow([])
    writer.writerow(['Lifetime downloads (all articles)', Article.objects.aggregate(total=Sum('download_count'))['total'] or 0])
    writer.writerow(['Lifetime citations (all articles)', Article.objects.aggregate(total=Sum('citation_count'))['total'] or 0])
    writer.writerow([])

    # -- Subscriptions / revenue --------------------------------------------
    active_subs = list(
        UserSubscription.objects.filter(
            status=UserSubscription.Status.ACTIVE, start_date__lte=today, end_date__gte=today,
        ).select_related('plan'),
    )
    plan_type_counts = {}
    for sub in active_subs:
        plan_type_counts[sub.plan.plan_type] = plan_type_counts.get(sub.plan.plan_type, 0) + 1
    writer.writerow(['Active Subscriptions by Plan Type'])
    writer.writerow(['Plan Type', 'Active Count'])
    for plan_type, label in SubscriptionPlan.PlanType.choices:
        writer.writerow([label, plan_type_counts.get(plan_type, 0)])
    writer.writerow([])

    writer.writerow(['Total active subscriptions', len(active_subs)])
    writer.writerow(['Approximate MRR', _mrr_estimate(active_subs)])
    writer.writerow([
        'Cancelled subscriptions (lifetime)',
        UserSubscription.objects.filter(status=UserSubscription.Status.CANCELLED).count(),
    ])
    writer.writerow(['Article purchases (lifetime count)', ArticlePurchase.objects.count()])
    writer.writerow([
        'Article purchase revenue (lifetime)',
        ArticlePurchase.objects.aggregate(total=Sum('amount'))['total'] or 0,
    ])
    writer.writerow([])

    # -- Ads -----------------------------------------------------------------
    ads_all_time_impressions = AdSlot.objects.aggregate(total=Sum('impression_count'))['total'] or 0
    ads_all_time_clicks = AdSlot.objects.aggregate(total=Sum('click_count'))['total'] or 0
    writer.writerow(['Ads — All-Time'])
    writer.writerow(['Impressions', ads_all_time_impressions])
    writer.writerow(['Clicks', ads_all_time_clicks])
    writer.writerow([
        'CTR (%)',
        round(ads_all_time_clicks / ads_all_time_impressions * 100, 2) if ads_all_time_impressions else '',
    ])
    writer.writerow([])

    recent_ad_events = AdEvent.objects.filter(occurred_at__gte=window_start)
    writer.writerow([f'Ads — Last {AnalyticsView.TREND_DAYS} Days'])
    writer.writerow(['Impressions', recent_ad_events.filter(event_type=AdEvent.EventType.IMPRESSION).count()])
    writer.writerow(['Clicks', recent_ad_events.filter(event_type=AdEvent.EventType.CLICK).count()])
    writer.writerow([])

    writer.writerow(['Top Ads (by clicks)'])
    writer.writerow(['Sponsor', 'Zone', 'Impressions', 'Clicks'])
    for ad in AdSlot.objects.order_by('-click_count', '-impression_count')[:5]:
        writer.writerow([ad.sponsor_name, ad.get_zone_display(), ad.impression_count, ad.click_count])
    writer.writerow([])

    # -- Newsletter ------------------------------------------------------------
    subscriber_counts = dict(Subscriber.objects.values_list('status').annotate(count=Count('id')).order_by())
    writer.writerow(['Newsletter Subscribers by Status'])
    writer.writerow(['Status', 'Count'])
    for status, label in Subscriber.Status.choices:
        writer.writerow([label, subscriber_counts.get(status, 0)])
    writer.writerow([])
    writer.writerow(['Newsletter issues sent (lifetime)', NewsletterIssue.objects.filter(sent_at__isnull=False).count()])
    writer.writerow([
        'Newsletter total recipients (lifetime)',
        NewsletterIssue.objects.aggregate(total=Sum('recipient_count'))['total'] or 0,
    ])
    writer.writerow([])

    # -- Pitches -----------------------------------------------------------
    writer.writerow([
        'Open story pitches (submitted or in review)',
        StoryPitch.objects.filter(status__in=[StoryPitch.Status.SUBMITTED, StoryPitch.Status.IN_REVIEW]).count(),
    ])

    return response


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class CommentModerationListView(ListView):
    """django_comments_xtd (see ajna_health_lens/settings.py) publishes
    comments immediately — there's no moderation queue upstream, just
    Django admin's generic changelist, which non-superuser editorial staff
    (is_staff=False) can't reach. This is that missing surface, scoped to
    the same role_required boundary as every other editorial screen.
    """

    model = XtdComment
    template_name = 'admin_custom/manage/comment_list.html'
    context_object_name = 'comments'
    paginate_by = 30

    def get_queryset(self):
        queryset = XtdComment.objects.select_related('content_type', 'user').order_by('-submit_date')
        status = self.request.GET.get('status')
        if status == 'removed':
            queryset = queryset.filter(is_removed=True)
        elif status == 'visible':
            queryset = queryset.filter(is_removed=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['selected_status'] = self.request.GET.get('status', '')
        return context


@role_required(*EDITORIAL_ROLES)
@require_POST
def comment_moderate(request, pk, action):
    if action not in ('remove', 'restore'):
        raise Http404

    comment = get_object_or_404(XtdComment, pk=pk)
    comment.is_removed = action == 'remove'
    comment.save(update_fields=['is_removed'])
    messages.success(request, f'Comment {"removed" if comment.is_removed else "restored"}.')
    return redirect('admin_custom:manage_comment_list')
