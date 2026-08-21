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
