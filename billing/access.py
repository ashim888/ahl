"""The real paywall gate — the single place that decides whether a given
user can read a given article's full text. articles.views.ArticleDetailView
is the only caller today; keep it that way so there's exactly one gate to
audit rather than the check being duplicated per view.
"""
import datetime

from django.utils import timezone

from .models import ArticleGift, ArticlePurchase, MeteredArticleRead, UserSubscription

# Session-based for an anonymous reader (mirrors articles.views._record_article_view's
# own session-key pattern), account-based once logged in. A reader who
# registers mid-period starts a fresh count under the account rather than
# carrying the session's count over — simplest correct behavior, not a
# perfect one (a reader could reset an anonymous count by registering a new
# account, same class of gap as any session-based limiter).
FREE_SAMPLE_LIMIT_PER_MONTH = 4
# pay_per_article is deliberately never metered — it's a one-off priced item
# by design (billing/models.py:ArticlePurchase), not a taste of a
# subscription; sampling it for free would undercut the very thing it
# exists to sell. open_access needs no metering — it's already unlimited.
METERED_ACCESS_TYPES = ('subscription',)


def user_has_active_subscription(user):
    if not user.is_authenticated:
        return False
    today = timezone.localdate()
    return UserSubscription.objects.filter(
        user=user, status=UserSubscription.Status.ACTIVE,
        start_date__lte=today, end_date__gte=today,
    ).exists()


def _active_subscription(user):
    """The user's current active UserSubscription (plan selected), or None.
    Internal — perk checks need to know *which* plan, not just whether one
    exists; external callers that only need the yes/no answer should use
    user_has_active_subscription above.
    """
    if not user.is_authenticated:
        return None
    today = timezone.localdate()
    return UserSubscription.objects.filter(
        user=user, status=UserSubscription.Status.ACTIVE,
        start_date__lte=today, end_date__gte=today,
    ).select_related('plan').order_by('-end_date').first()


def user_has_perk(user, perk_field_name):
    """Whether the user's active plan grants a specific SubscriptionPlan
    boolean field (e.g. 'grants_ad_free_reading') — False for no active
    subscription, or an active subscription whose plan has that perk turned
    off. Every plan defaults both perk fields to True (see
    billing/models.py), so this is a behavior-preserving replacement for
    "has any active subscription" everywhere it's used below, until an
    editor actually configures a plan differently.
    """
    subscription = _active_subscription(user)
    return bool(subscription and getattr(subscription.plan, perk_field_name, False))


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

    This is the *real* entitlement check only — it deliberately does not
    know about the metered free-sample allowance (see consume_free_sample
    below), since that's a one-time, stateful grant rather than a durable
    "yes/no" a caller can safely re-check. Article/view code that also wants
    to honor a free sample calls consume_free_sample separately when this
    returns False for a METERED_ACCESS_TYPES article.
    """
    if article.access_type == article.AccessType.OPEN_ACCESS:
        return True
    if user.is_authenticated and getattr(user, 'is_editorial_staff', False):
        return True
    if user_has_perk(user, 'grants_unlimited_articles'):
        return True
    if article.access_type == article.AccessType.PAY_PER_ARTICLE:
        return user_has_purchased_article(user, article)
    return False


def _current_period():
    today = timezone.localdate()
    return f'{today.year:04d}-{today.month:02d}'


def _metered_reads_queryset(request, period):
    """Scoped to the current reader (account or session) and period. Returns
    an empty (but real) queryset, not None, for an anonymous reader with no
    session key yet — see consume_free_sample for why that case fails
    closed rather than granting unlimited access.
    """
    if request.user.is_authenticated:
        return MeteredArticleRead.objects.filter(user=request.user, period=period)
    session_key = request.session.session_key
    if not session_key:
        return MeteredArticleRead.objects.none()
    return MeteredArticleRead.objects.filter(session_key=session_key, period=period, user__isnull=True)


def free_sample_reads_used(request):
    """How many distinct articles this reader has already drawn from the
    free-sample quota this period — for display (e.g. "2 of 4 free articles
    used this month"), not itself a gating decision.
    """
    return _metered_reads_queryset(request, _current_period()).values('article').distinct().count()


def consume_free_sample(request, article):
    """Grants access to `article` under the metered free-sample quota if the
    reader has any left this period, recording the read so it counts against
    future checks. Returns True if access is granted this way (the caller
    should treat that exactly like a real entitlement for this request), or
    False if the article isn't a METERED_ACCESS_TYPES type or the quota is
    already used up.

    Only meaningful to call for a METERED_ACCESS_TYPES article the reader
    doesn't already have real access to (article_is_accessible returned
    False) — a subscriber or purchaser never reaches this, since they
    already passed the real gate.
    """
    if article.access_type not in METERED_ACCESS_TYPES:
        return False
    period = _current_period()
    queryset = _metered_reads_queryset(request, period)
    if queryset.filter(article=article).exists():
        return True  # already sampled this article this period — a free re-read, not a fresh charge against quota
    if queryset.values('article').distinct().count() >= FREE_SAMPLE_LIMIT_PER_MONTH:
        return False
    if request.user.is_authenticated:
        MeteredArticleRead.objects.create(user=request.user, article=article, period=period)
        return True
    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key
    if not session_key:
        # Can't reliably track this reader at all — fail closed (deny the
        # free sample) rather than risk granting effectively unlimited free
        # access to every sessionless request.
        return False
    MeteredArticleRead.objects.create(session_key=session_key, article=article, period=period)
    return True


# Same restriction, and the same reason, as METERED_ACCESS_TYPES above —
# pay_per_article is a one-off priced item, gifting it for free would
# undercut the thing it exists to sell; open_access needs no gift, it's
# already unlimited.
GIFTABLE_ACCESS_TYPES = ('subscription',)
GIFT_LINK_VALID_DAYS = 14


def gift_articles_remaining(user):
    """How many more distinct articles `user` can gift this period, per
    their active plan's gift_articles_per_month allowance. 0 for a
    non-subscriber or a plan with gifting turned off (the default — see
    SubscriptionPlan.gift_articles_per_month).
    """
    subscription = _active_subscription(user)
    if not subscription or subscription.plan.gift_articles_per_month <= 0:
        return 0
    used = ArticleGift.objects.filter(gifter=user, period=_current_period()).values('article').distinct().count()
    return max(0, subscription.plan.gift_articles_per_month - used)


def get_existing_article_gift(user, article):
    """The gift `user` already created for `article` this period, if any —
    for display (e.g. showing the existing link instead of a "create"
    button) without creating anything or touching the quota.
    """
    if not user.is_authenticated:
        return None
    return ArticleGift.objects.filter(gifter=user, article=article, period=_current_period()).first()


def create_or_get_article_gift(user, article):
    """Returns an ArticleGift the caller can build a shareable link from, or
    None if `article` isn't giftable or the user has no gift allowance left
    this period. Regenerating for an article already gifted this period
    returns the existing row (same link, same expiry) rather than consuming
    a second slot of the monthly allowance — see ArticleGift's own
    docstring.
    """
    if article.access_type not in GIFTABLE_ACCESS_TYPES:
        return None
    period = _current_period()
    existing = ArticleGift.objects.filter(gifter=user, article=article, period=period).first()
    if existing:
        return existing
    if gift_articles_remaining(user) <= 0:
        return None
    return ArticleGift.objects.create(
        gifter=user, article=article, period=period,
        expires_at=timezone.now() + datetime.timedelta(days=GIFT_LINK_VALID_DAYS),
    )


def get_valid_article_gift(article, token):
    """The ArticleGift for this exact (article, token) pair, or None if it
    doesn't exist or has expired — the single check articles.views.
    article_gift_view relies on to decide whether to grant free access.
    """
    gift = ArticleGift.objects.filter(article=article, token=token).select_related('gifter').first()
    if gift is None or gift.is_expired:
        return None
    return gift
