from django.conf import settings
from django.db import models
from django.utils import timezone


class PlanFeature(models.Model):
    """One row in the plan-comparison table (e.g. "Ad-free reading"). A
    global, ordered list — plans opt in via SubscriptionPlan.features below,
    so every plan's detail page and the browse page's comparison table
    render the exact same row order with a ✓/— per plan.
    """

    label = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.label


class SubscriptionPlan(models.Model):
    """A recurring plan a reader can be subscribed to. Self-serve checkout
    exists (billing/gateway.py — StubGateway, no real processor yet); these
    can also be granted manually via UserSubscription below.
    """

    class PlanType(models.TextChoices):
        INDIVIDUAL_MONTHLY = 'individual_monthly', 'Individual — Monthly'
        INDIVIDUAL_ANNUAL = 'individual_annual', 'Individual — Annual'
        INSTITUTIONAL = 'institutional', 'Institutional'

    name = models.CharField(max_length=100)
    plan_type = models.CharField(max_length=30, choices=PlanType.choices)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    duration_days = models.PositiveIntegerField(
        help_text='Length of access granted per billing cycle, e.g. 30 for monthly or 365 for annual.',
    )
    description = models.TextField(blank=True)
    features = models.ManyToManyField(
        PlanFeature, blank=True, related_name='plans',
        help_text='What a subscriber on this plan gets — shown on the plan detail page and the pricing comparison table.',
    )
    # Real, enforced access — distinct from `features` above, which is a
    # free-text marketing list only ever rendered, never checked. Before
    # these existed, billing.access.article_is_accessible and
    # ads.services.is_ad_free_reader both granted the same access to every
    # active subscription regardless of plan/price, so the pricing page's
    # comparison table was promising differentiation the backend didn't
    # enforce. Default True on both so every existing/seeded plan keeps
    # today's behavior unchanged; a future lower/limited tier can flip
    # either off per plan, from this same manage screen, no code change.
    grants_ad_free_reading = models.BooleanField(
        default=True, help_text='Subscribers on this plan never see ads (billing.access/ads.services).',
    )
    grants_unlimited_articles = models.BooleanField(
        default=True,
        help_text='Subscribers on this plan bypass both the subscription-tier paywall and the metered '
                   'free-sample limit entirely (billing.access.article_is_accessible).',
    )
    # Default False, unlike the two perks above — this is a brand-new
    # capability (newsletter/models.py:NewsletterIssue.Audience.PREMIUM),
    # not a pre-existing behavior to preserve. No plan claims to grant it
    # until an editor deliberately opts one in.
    grants_premium_newsletter = models.BooleanField(
        default=False,
        help_text='Subscribers on this plan receive newsletter issues sent to "Premium subscribers only" '
                   '(newsletter.recipients.confirmed_recipients), in addition to every regular issue.',
    )
    is_featured = models.BooleanField(
        default=False, help_text='Highlight as "Most Popular" on the pricing page.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['price']

    def __str__(self):
        return f'{self.name} (₹{self.price})'


class UserSubscription(models.Model):
    """A reader's subscription window. Today these are created by editorial
    staff granting access by hand (comp accounts, institutional deals, manual
    bank transfer) — see billing/views.py grant_subscription. A Stripe
    integration would create these from webhook events instead, without
    changing how access is checked (see billing/access.py).
    """

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        CANCELLED = 'cancelled', 'Cancelled'
        EXPIRED = 'expired', 'Expired'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscriptions',
    )
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField()
    # TODO: Integrate Stripe — store the Stripe subscription/customer id here
    # once checkout exists; blank for manually-granted subscriptions.
    payment_reference = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} — {self.plan}'

    @property
    def is_currently_active(self):
        return self.status == self.Status.ACTIVE and self.start_date <= timezone.localdate() <= self.end_date


class ArticlePurchase(models.Model):
    """A one-time grant of access to exactly one pay-per-article ("special")
    article — distinct from a time-boxed UserSubscription. Also manually
    granted for now (see billing/views.py grant_purchase); a Stripe
    integration would create these from a successful PaymentIntent instead.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='article_purchases',
    )
    article = models.ForeignKey('articles.Article', on_delete=models.CASCADE, related_name='purchases')
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    # TODO: Integrate Stripe — store the PaymentIntent id here once checkout exists.
    payment_reference = models.CharField(max_length=255, blank=True)
    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchased_at']
        unique_together = ('user', 'article')

    def __str__(self):
        return f'{self.user} bought {self.article}'


class MeteredArticleRead(models.Model):
    """One row per (reader, article, calendar-month) — records a free-sample
    consumption against the metered-paywall quota (see
    billing.access.consume_free_sample). Distinct from
    articles.ArticleView, which records every page view for the homepage's
    Trending widget regardless of tier/quota and de-duplicates on a 30-minute
    window, not a calendar month — the two models serve different purposes
    and are deliberately not merged.

    `user` is set for an authenticated reader, `session_key` for an
    anonymous one — never both, matching the split already used by
    articles.views._record_article_view for the same reason (an anonymous
    reader has no account to key on). A reader re-reading the same article
    within the same period doesn't consume a second slot — see
    consume_free_sample's own idempotency check before creating a row here.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='metered_reads',
    )
    session_key = models.CharField(max_length=40, blank=True)
    article = models.ForeignKey('articles.Article', on_delete=models.CASCADE, related_name='metered_reads')
    period = models.CharField(max_length=7, help_text='Calendar-month bucket, e.g. "2026-09".')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-read_at']
        indexes = [
            models.Index(fields=['user', 'period']),
            models.Index(fields=['session_key', 'period']),
        ]

    def __str__(self):
        reader = self.user or f'session {self.session_key[:8]}'
        return f'{reader} read {self.article} free ({self.period})'
