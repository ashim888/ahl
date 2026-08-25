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
        """Every zone name embeds its required IAB ad size so it's never
        ambiguous which dimensions to design/export for — the same string
        shows up in the manage-list filter, the create/edit form's Zone
        select, and admin/list-display everywhere `get_zone_display()` is
        used. Actual pixel dimensions live in ZONE_DIMENSIONS below (used
        for upload validation and render sizing) — kept as a separate dict
        rather than parsed out of the label text, so the two can never
        silently drift out of sync from a label copy-edit.
        """
        HEADER_LEADERBOARD = 'header_leaderboard', 'Site Header — Leaderboard (728×90)'
        MOBILE_ANCHOR = 'mobile_anchor', 'Mobile Anchor Banner (320×50)'
        MOBILE_LARGE_BANNER = 'mobile_large_banner', 'Mobile — Large Banner (320×100)'
        # Three same-size slots, not one — a single 300×250 box centered in
        # the ~1232px homepage feed container leaves large empty margins on
        # both sides. Rendered side by side (templates/home.html) so however
        # many of the three an editor has actually filled in fill that width
        # instead of one narrow box floating in the middle of it. Slot 1 keeps
        # the original 'homepage_rectangle' value (only its label gained the
        # "1") since its size/shape hasn't changed; 2 and 3 are new.
        HOMEPAGE_RECTANGLE_1 = 'homepage_rectangle', 'Homepage Feed — Medium Rectangle 1 (300×250)'
        HOMEPAGE_RECTANGLE_2 = 'homepage_rectangle_2', 'Homepage Feed — Medium Rectangle 2 (300×250)'
        HOMEPAGE_RECTANGLE_3 = 'homepage_rectangle_3', 'Homepage Feed — Medium Rectangle 3 (300×250)'
        # Was a 300×600 Half Page — tall but only 300px wide, leaving large
        # empty margins either side in the same ~1232px container the three
        # rectangles above sit in. A 728×90 Leaderboard spans that width
        # properly instead. Value renamed along with the constant/label (not
        # left as the stale 'homepage_half_page') so nothing about this zone
        # still claims to be a half page — see migration 0006, which follows
        # 0004's precedent for remapping any AdSlot rows already sold under
        # the old zone rather than orphaning them.
        HOMEPAGE_LEADERBOARD = 'homepage_leaderboard', 'Homepage — Leaderboard (728×90)'
        ARTICLE_IN_CONTENT = 'article_in_content', 'In-Article — Large Rectangle (336×280)'
        # Injected between paragraphs partway through a long article's body
        # (articles/content_ads.py + article_detail.html), not a fixed
        # placement — alternates with ARTICLE_IN_CONTENT (rectangle) at each
        # injection point rather than getting its own separate rectangle
        # zone, so a longer article doesn't read as one shape breaking it up
        # over and over. Same 728×90 shape as the site's other leaderboards
        # (kept consistent rather than inventing a third banner size), auto-
        # scaled down by the existing responsive max-width handling to fit
        # the ~699px article column.
        ARTICLE_CONTENT_BANNER = 'article_content_banner', 'Article Body — Banner (728×90)'
        ARTICLE_SIDEBAR = 'article_sidebar', 'Article Sidebar — Medium Rectangle (300×250)'
        # Was a 160×600 Wide Skyscraper in a sidebar column that renders at
        # ~379px wide — under half the column filled. 300×600 (a Half Page,
        # not a Skyscraper — value renamed along with it, see migration 0006)
        # uses most of that width instead.
        ARTICLE_SIDEBAR_HALF_PAGE = 'article_sidebar_half_page', 'Article Sidebar — Half Page (300×600)'

    # Standard IAB ad unit sizes (px) — the single source of truth for both
    # upload-time validation (AdSlotForm.clean, "an ad this size" not "an ad
    # under N MB of any shape") and render-time sizing (the `ad_slot`
    # template tag) — see ARCHITECTURE.md §4.11. Every zone maps to exactly
    # one size; the same size can legitimately be reused across zones (e.g.
    # Medium Rectangle for both the homepage feed and the article sidebar)
    # since it's a real, common placement for that unit.
    ZONE_DIMENSIONS = {
        Zone.HEADER_LEADERBOARD: (728, 90),
        Zone.MOBILE_ANCHOR: (320, 50),
        Zone.MOBILE_LARGE_BANNER: (320, 100),
        Zone.HOMEPAGE_RECTANGLE_1: (300, 250),
        Zone.HOMEPAGE_RECTANGLE_2: (300, 250),
        Zone.HOMEPAGE_RECTANGLE_3: (300, 250),
        Zone.HOMEPAGE_LEADERBOARD: (728, 90),
        Zone.ARTICLE_IN_CONTENT: (336, 280),
        Zone.ARTICLE_CONTENT_BANNER: (728, 90),
        Zone.ARTICLE_SIDEBAR: (300, 250),
        Zone.ARTICLE_SIDEBAR_HALF_PAGE: (300, 600),
    }

    sponsor_name = models.CharField(max_length=255)
    zone = models.CharField(max_length=30, choices=Zone.choices)
    image = models.ImageField(
        upload_to='ads/%Y/%m/',
        validators=[ad_image_extension_validator, validate_ad_image_size],
        help_text='JPG or PNG, up to 5 MB. Must exactly match the pixel dimensions '
                   "required by the selected zone — see the size reference on this form.",
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
    def width(self):
        return self.ZONE_DIMENSIONS[self.zone][0]

    @property
    def height(self):
        return self.ZONE_DIMENSIONS[self.zone][1]

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
