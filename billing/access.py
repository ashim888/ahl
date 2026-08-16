"""The real paywall gate — the single place that decides whether a given
user can read a given article's full text. articles.views.ArticleDetailView
is the only caller today; keep it that way so there's exactly one gate to
audit rather than the check being duplicated per view.
"""
from django.utils import timezone

from .models import ArticlePurchase, UserSubscription


def user_has_active_subscription(user):
    if not user.is_authenticated:
        return False
    today = timezone.localdate()
    return UserSubscription.objects.filter(
        user=user, status=UserSubscription.Status.ACTIVE,
        start_date__lte=today, end_date__gte=today,
    ).exists()


def user_has_purchased_article(user, article):
    if not user.is_authenticated:
        return False
    return ArticlePurchase.objects.filter(user=user, article=article).exists()


def article_is_accessible(user, article):
    """Free articles are always accessible. Editorial staff always see full
    text (they're already gated to that role elsewhere — this just lets them
    read/QA gated content). Subscribers can read both subscription-tier and
    pay-per-article ("special") articles — pay-per-article exists for readers
    who don't want a subscription, not as an extra charge on top of one.
    """
    if article.access_type == article.AccessType.OPEN_ACCESS:
        return True
    if user.is_authenticated and getattr(user, 'is_editorial_staff', False):
        return True
    if user_has_active_subscription(user):
        return True
    if article.access_type == article.AccessType.PAY_PER_ARTICLE:
        return user_has_purchased_article(user, article)
    return False
