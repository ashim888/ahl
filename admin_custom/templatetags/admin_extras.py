from django import template

from articles.models import Article

register = template.Library()


@register.simple_tag
def recent_draft_articles(limit=4):
    """For the sidebar's "Draft articles" quick-list, shown on every admin
    page — a simple_tag (not a context processor) so the query only runs
    when the admin dashboard shell actually renders, not on every public page.
    """
    return Article.objects.filter(status=Article.Status.DRAFT).order_by('-updated_at')[:limit]


@register.simple_tag
def pending_work_counts():
    """Badge counts for the sidebar's Verification Queue, Pitch Queue and
    Comments links — previously the Dashboard home KPI row was the only "what needs
    attention" surface, invisible if an editor lands anywhere else first.
    Same simple_tag pattern as recent_draft_articles, for the same reason
    (query only runs when the admin shell renders).
    """
    import datetime

    from django.utils import timezone
    from django_comments_xtd.models import XtdComment
    from articles.models import Article
    from pitches.models import StoryPitch
    from users.models import User

    return {
        # Comments publish immediately (no pre-moderation queue), so the
        # useful signal is "new since yesterday" — what an editor should
        # glance over — not a backlog count.
        'new_comments': XtdComment.objects.filter(
            is_public=True, is_removed=False,
            submit_date__gte=timezone.now() - datetime.timedelta(hours=24),
        ).count(),
        'pending_verifications': User.objects.filter(
            verification_status=User.VerificationStatus.PENDING,
        ).count(),
        # Stories waiting on an editor's review (see Article.Status).
        'articles_in_review': Article.objects.filter(status=Article.Status.IN_REVIEW).count(),
        'open_pitches': StoryPitch.objects.filter(
            status__in=[StoryPitch.Status.SUBMITTED, StoryPitch.Status.IN_REVIEW],
        ).count(),
    }
