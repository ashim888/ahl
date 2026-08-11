from django.db.models import Count
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from articles.models import Article
from peer_review.models import Review
from submissions.models import Submission
from users.decorators import role_required
from users.models import User

EDITORIAL_ROLES = (User.Role.EDITOR, User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class DashboardHomeView(TemplateView):
    """Editorial Command Center — lightweight version of the KPI dashboard
    described in ARCHITECTURE.md §4.6 / ROADMAP.md Phase 7. Built now, ahead
    of Phase 7, since the sidebar shell needed a landing page.
    """

    template_name = 'admin_custom/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        article_counts = dict(
            Article.objects.values_list('status').annotate(count=Count('id')).order_by(),
        )
        context['article_counts'] = {
            label: article_counts.get(value, 0) for value, label in Article.Status.choices
        }
        context['article_total'] = sum(article_counts.values())

        submission_counts = dict(
            Submission.objects.values_list('status').annotate(count=Count('id')).order_by(),
        )
        context['submission_counts'] = {
            label: submission_counts.get(value, 0) for value, label in Submission.Status.choices
        }
        context['submission_total'] = sum(submission_counts.values())

        context['pending_verifications'] = User.objects.filter(
            verification_status=User.VerificationStatus.PENDING,
        ).count()

        active_review_statuses = (Review.Status.INVITED, Review.Status.ACCEPTED)
        context['pending_reviews'] = Review.objects.filter(status=Review.Status.INVITED).count()
        context['active_reviews'] = Review.objects.filter(status__in=active_review_statuses).count()
        context['overdue_reviews'] = Review.objects.filter(
            status__in=active_review_statuses, due_date__lt=timezone.now().date(),
        ).count()

        context['recent_submissions'] = Submission.objects.select_related(
            'submitter', 'editor_assigned',
        ).order_by('-submission_date')[:5]

        return context
