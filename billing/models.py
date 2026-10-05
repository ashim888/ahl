import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from .money import format_money


def generate_gift_token():
    return secrets.token_urlsafe(32)


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
    # A quantity, not a boolean, unlike the three perks above — "share a
    # limited number of premium articles a month" is inherently about how
    # many, and different plans may reasonably get different allowances
    # (e.g. an Institutional plan gifting more than an Individual one).
    # Default 0 (disabled), same "brand-new capability" reasoning as
    # grants_premium_newsletter — no plan claims to grant this until an
    # editor deliberately sets an allowance.
    gift_articles_per_month = models.PositiveIntegerField(
        default=0,
        help_text='How many distinct subscription-tier articles a subscriber on this plan can gift to '
                   'non-subscribers each month, via a shareable link (billing.access.create_or_get_article_gift). '
                   '0 disables gifting for this plan.',
    )
    # Default False, same "brand-new capability" reasoning as
    # grants_premium_newsletter/gift_articles_per_month — an archived
    # article requires this regardless of what access_type it had while
    # still active (see billing.access.article_is_accessible), so a
    # once-free article doesn't stay free forever purely by accident.
    grants_full_archive = models.BooleanField(
        default=False,
        help_text='Subscribers on this plan can read archived (Article.Status.ARCHIVED) articles in full, '
                   'regardless of the access tier those articles had while still active.',
    )
    is_featured = models.BooleanField(
        default=False, help_text='Highlight as "Most Popular" on the pricing page.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['price']

    def __str__(self):
        return f'{self.name} ({format_money(self.price)})'


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
    # Which expiry emails went out ("7", "1", "ended") — see billing/reminders.py.
    reminders_sent = models.JSONField(default=list, blank=True)

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


class ArticleGift(models.Model):
    """A subscriber-generated shareable link granting anyone who has it free
    access to one subscription-tier article — "gift articles" (ROADMAP.md
    Phase 10). No claim/recipient step: whoever opens the link reads the
    article, the same way NYT/WaPo gift links work, not a single-use invite.

    One row per (gifter, article, calendar-month) — regenerating a link for
    the same article within the same month returns the existing row rather
    than consuming a second slot of the gifter's monthly allowance (see
    billing.access.create_or_get_article_gift), matching
    MeteredArticleRead's own re-read-is-free precedent.
    """

    gifter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='article_gifts_given',
    )
    article = models.ForeignKey('articles.Article', on_delete=models.CASCADE, related_name='gift_links')
    token = models.CharField(max_length=64, unique=True, default=generate_gift_token)
    period = models.CharField(max_length=7, help_text='Calendar-month bucket, e.g. "2026-09".')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        unique_together = ('gifter', 'article', 'period')

    def __str__(self):
        return f'{self.gifter} gifted {self.article}'

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at


def generate_payment_reference() -> str:
    """Unique, alphanumeric-only, <= 30 chars — Fonepay's referenceLabel rules."""
    return 'AHL' + secrets.token_hex(10).upper()


class Organization(models.Model):
    """An institution (hospital, university, NGO) whose staff read under one
    subscription: anyone with a confirmed email address at one of its
    domains gets the plan's access while the deal is current. Set up by
    senior staff after a deal is agreed (/manage/billing/organizations/);
    there's no self-serve checkout for these.
    """

    name = models.CharField(max_length=255)
    email_domains = models.TextField(
        help_text='One per line, e.g. nhrc.gov.np. Addresses at subdomains (staff@dept.nhrc.gov.np) count too. '
                  'Public email providers (gmail.com and the like) are refused.',
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name='organizations',
        help_text='Decides what members get (ad-free, archive, gifting…).',
    )
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField()
    seats = models.PositiveIntegerField(
        null=True, blank=True, help_text='Most people who can join. Leave empty for no limit.',
    )
    is_active = models.BooleanField(default=True, help_text='Untick to stop access straight away.')
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True, help_text='Gets the receipt for payments recorded against this organization.')
    notes = models.TextField(blank=True, help_text='Staff only — contract details, invoice numbers.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def domains(self) -> list[str]:
        return [line.strip().lower().lstrip('@') for line in self.email_domains.splitlines() if line.strip()]

    def matches_email(self, email: str) -> bool:
        domain = (email or '').rpartition('@')[2].lower()
        return bool(domain) and any(domain == d or domain.endswith(f'.{d}') for d in self.domains)

    @property
    def is_current(self) -> bool:
        return self.is_active and self.start_date <= timezone.localdate() <= self.end_date

    @property
    def seats_left(self):
        return None if self.seats is None else max(self.seats - self.members.count(), 0)


class OrganizationMember(models.Model):
    """Someone reading under an Organization — recorded the first time
    their confirmed email gets them access, for seat counting and the
    usage figures an institution asks for."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='organization_memberships')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-joined_at']
        unique_together = ('organization', 'user')

    def __str__(self):
        return f'{self.user} at {self.organization}'


class ReceiptSequence(models.Model):
    """Hands out gap-free receipt numbers (billing/payments.py
    next_receipt_number) — one row, locked while a number is taken, so two
    payments confirmed at the same moment never share or skip a number."""

    name = models.CharField(max_length=30, unique=True)
    last_number = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f'{self.name}: {self.last_number}'


class Payment(models.Model):
    """Every payment that bought access — the one money ledger. Fonepay
    checkouts start Pending and are confirmed only by a server-side status
    check (billing/payments.py verify_payment); payments staff record by
    hand (bank transfer, cheque) and the development stub gateway are
    created already Paid. Access — the subscription, article purchase or
    course enrollment — is granted exactly once, on the transition to Paid,
    which also assigns the receipt number and emails the receipt.

    Prices are VAT-exclusive: `subtotal` is the price, `vat_amount` the VAT
    on top, `amount` what was actually paid (subtotal + VAT).
    """

    class Kind(models.TextChoices):
        SUBSCRIPTION = 'subscription', 'Subscription'
        ARTICLE = 'article', 'Article purchase'
        COURSE = 'course', 'Training course'
        INSTITUTIONAL = 'institutional', 'Institutional subscription'

    class Gateway(models.TextChoices):
        FONEPAY = 'fonepay', 'Fonepay'
        MANUAL = 'manual', 'Recorded by staff'
        STUB = 'stub', 'Test gateway'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Waiting for payment'
        SUCCESS = 'success', 'Paid'
        FAILED = 'failed', 'Failed'
        EXPIRED = 'expired', 'Expired'
        REFUNDED = 'refunded', 'Refunded'

    # Empty only for an institutional payment (the organization paid).
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='payments',
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, null=True, blank=True, related_name='payments',
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    article = models.ForeignKey('articles.Article', on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    course = models.ForeignKey('training.TrainingCourse', on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='Price before VAT.')
    vat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text='Total paid, VAT included.')
    description = models.CharField(max_length=255)
    gateway = models.CharField(max_length=20, choices=Gateway.choices, default=Gateway.FONEPAY)
    receipt_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    # Who the receipt was made out to, frozen when the payment completed —
    # receipts are tax records and must stay readable even after the payer
    # deletes their account (users/privacy.py erase_user).
    billed_name = models.CharField(max_length=255, blank=True)
    billed_email = models.EmailField(blank=True)
    # Where to send the reader after paying (e.g. the article whose paywall
    # they subscribed from) — a site-relative path, checked when set.
    return_path = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text='The staff member who recorded a manual payment.',
    )
    # Something a person should look at — set when a paid payment couldn't
    # be granted cleanly (already owned, course over capacity…). Shown on
    # the Payments screen; cleared by staff once handled.
    attention = models.CharField(max_length=255, blank=True)
    # Refunds (billing/payments.py refund_payment): always the full amount,
    # money returned outside the site (bank transfer / Fonepay merchant
    # portal); recording it here removes the access and issues a credit note.
    refunded_at = models.DateTimeField(null=True, blank=True)
    refunded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    refund_reason = models.TextField(blank=True)
    credit_note_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    reference = models.CharField(max_length=30, unique=True, default=generate_payment_reference)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    qr_message = models.TextField(blank=True, help_text='Fonepay QR payload, shown as a QR or passed to a bank app.')
    websocket_url = models.CharField(max_length=500, blank=True)
    gateway_trace_id = models.CharField(max_length=64, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True, help_text='Last status response from the gateway.')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self):
        return f'{self.reference} — {self.description} ({self.get_status_display()})'

    @property
    def is_expired(self) -> bool:
        return self.status == self.Status.PENDING and timezone.now() >= self.expires_at

    @property
    def payer_name(self) -> str:
        if self.billed_name:
            return self.billed_name
        if self.organization_id:
            return self.organization.name
        return self.user.get_full_name() or self.user.email if self.user_id else ''

    @property
    def payer_email(self) -> str:
        if self.billed_email:
            return self.billed_email
        if self.organization_id:
            return self.organization.contact_email
        return self.user.email if self.user_id else ''
