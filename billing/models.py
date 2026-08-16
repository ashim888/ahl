from django.conf import settings
from django.db import models
from django.utils import timezone


class SubscriptionPlan(models.Model):
    """A recurring plan a reader can be subscribed to. Checkout doesn't exist
    yet (see ROADMAP.md Phase 7) — for now these are created by editorial
    staff and granted to readers manually via UserSubscription below.
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
