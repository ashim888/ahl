from django.db import models
from django.utils import timezone

from .validators import ad_image_extension_validator, validate_ad_image_size


class AdSlot(models.Model):
    """A house/direct-sold ad — no ad network (Google AdSense, etc.)
    integration; August 2026 decision, see ROADMAP.md. Editors arrange and
    price sponsorships themselves and just enter the creative here. Never
    shown to a reader with an active subscription — see
    billing.access.user_has_active_subscription and ads/services.py — since
    "ad-free reading" is a subscriber perk already promised at signup.
    """

    class Zone(models.TextChoices):
        HOMEPAGE = 'homepage', 'Homepage'
        ARTICLE_SIDEBAR = 'article_sidebar', 'Article Page — Sidebar'

    sponsor_name = models.CharField(max_length=255)
    zone = models.CharField(max_length=30, choices=Zone.choices)
    image = models.ImageField(
        upload_to='ads/%Y/%m/',
        validators=[ad_image_extension_validator, validate_ad_image_size],
        help_text='JPG or PNG, up to 5 MB.',
    )
    link_url = models.URLField(help_text="Where a click sends the reader — the sponsor's page, not this site.")
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True, help_text='Leave blank to run indefinitely.')
    impression_count = models.PositiveIntegerField(default=0)
    click_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.sponsor_name} — {self.get_zone_display()}'

    @property
    def is_currently_active(self):
        today = timezone.localdate()
        if not self.is_active or self.start_date > today:
            return False
        if self.end_date and self.end_date < today:
            return False
        return True

    @property
    def ctr(self):
        """Click-through rate as a percentage, rounded to 2dp. None (not 0)
        with zero impressions — an ad that hasn't run yet has no rate, not a
        0% one; the template shows "—" for that case instead of a misleading number.
        """
        if not self.impression_count:
            return None
        return round(self.click_count / self.impression_count * 100, 2)


class AdEvent(models.Model):
    """One impression or click event — first-party, timestamped, same pattern
    as articles.ArticleView. AdSlot.impression_count/click_count (above) stay
    as cheap running totals for the list page; this event log is what makes a
    real day-by-day CTR trend possible (see ads/services.py and
    admin_custom's Analytics page), not just an all-time number.
    """

    class EventType(models.TextChoices):
        IMPRESSION = 'impression', 'Impression'
        CLICK = 'click', 'Click'

    ad_slot = models.ForeignKey(AdSlot, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['ad_slot', 'event_type', 'occurred_at'])]

    def __str__(self):
        return f'{self.get_event_type_display()} on {self.ad_slot} at {self.occurred_at}'
