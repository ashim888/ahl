import datetime

from django.db.models import Count
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from articles.models import Article
from training.models import Enrollment, TrainingCourse
from users.decorators import role_required
from users.models import User

EDITORIAL_ROLES = (User.Role.EDITOR, User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)

# Palette for the "Articles by Type" donut — chosen for contrast against
# white cards and against each other; order doesn't matter, slices are
# assigned by descending count so the biggest slice always gets the first color.
TYPE_CHART_COLORS = ['#7c6fea', '#34d399', '#fbbf24', '#60a5fa', '#f87171', '#22d3ee', '#f472b6', '#a3a3a3']


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class DashboardHomeView(TemplateView):
    """Editorial Command Center — KPIs and activity charts for the news site
    + editorial workspace (see CLAUDE.md SCOPE NOTE). Deliberately has no
    submission/peer-review metrics — those apps are dormant post-OJS-pivot.
    """

    template_name = 'admin_custom/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()

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

        # -- "Articles Created vs Published" bar chart, last 7 days -------
        days = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]
        daily_stats = []
        for day in days:
            created = Article.objects.filter(created_at__date=day).count()
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
