import secrets
import string

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .validators import (
    article_image_extension_validator, article_pdf_extension_validator,
    validate_article_pdf_size, validate_featured_image_size,
)

# Shared with articles/views.py HomeView, which caches under this key —
# defined here (not there) so Article.save() can invalidate it without
# models.py importing from views.py.
HOME_SECTIONS_CACHE_KEY = 'home:sections:v2'

# 5 lowercase-alphanumeric chars, e.g. "3f2a4" — short enough to be a usable
# permalink (/articles/3f2a4/, see articles/converters.py + urls.py), long
# enough that 36**5 (~60M) combinations make a collision on any one retry
# vanishingly unlikely, matching the retry-loop pattern Article.save() uses.
SHORT_CODE_ALPHABET = string.ascii_lowercase + string.digits
SHORT_CODE_LENGTH = 5


def generate_short_code():
    return ''.join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))


class Keyword(models.Model):
    """A normalized tag, replacing what used to be a raw comma-separated
    string on Article.keywords (August 2026) — the free-text version let
    the same concept fragment into several different spellings ("Diabetes"/
    "diabetes"/"Type 2 Diabetes"), which made keyword search a fragile
    substring match on a joined blob instead of a real lookup. `slug` (not
    `name`) is the actual identity for dedup/lookup purposes — case and
    punctuation differences in `name` fold to the same slug via
    Article.keyword_tags's get_or_create in articles/forms.py, so an editor
    typing "Diabetes" when "diabetes" already exists reuses the same row
    rather than creating a near-duplicate.
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Article(models.Model):
    """A published (or in-production) piece of content.

    Created by promoting an accepted Submission — see `submission` below —
    or, for non-peer-reviewed content (editorials, news), created directly
    by an editor.
    """

    class ArticleType(models.TextChoices):
        ORIGINAL_RESEARCH = 'original_research', 'Original Research'
        REVIEW_ARTICLE = 'review_article', 'Review Article'
        CASE_REPORT = 'case_report', 'Case Report'
        SHORT_COMMUNICATION = 'short_communication', 'Short Communication'
        METHODOLOGY_PAPER = 'methodology_paper', 'Methodology Paper'
        EDITORIAL = 'editorial', 'Editorial'
        NEWS_COMMENTARY = 'news_commentary', 'News & Commentary'
        LETTER_TO_EDITOR = 'letter_to_editor', 'Letter to Editor'

    class AccessType(models.TextChoices):
        OPEN_ACCESS = 'open_access', 'Free'
        SUBSCRIPTION = 'subscription', 'Subscription'
        PAY_PER_ARTICLE = 'pay_per_article', 'Pay-per-article (special)'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        ARCHIVED = 'archived', 'Archived'

    class HomepageSection(models.TextChoices):
        HERO = 'hero', 'Hero (top story)'
        LATEST_NEWS = 'latest_news', 'Latest News'
        OPINION = 'opinion', 'Opinion & Editorial'
        RESEARCH = 'research', 'Research Highlights'

    title = models.CharField(max_length=500)
    slug = models.SlugField(
        max_length=500, unique=True, blank=True,
        help_text='Leave blank to generate from the title (plus a short unique code, e.g. "my-article-3f2a4").',
    )
    short_code = models.CharField(
        max_length=SHORT_CODE_LENGTH, unique=True, blank=True, editable=False,
        help_text='Auto-generated permalink code — also reachable at /articles/<code>/.',
    )
    abstract = models.TextField()
    # Was a flat comma-separated CharField (pre-August 2026) — replaced with
    # a real M2M to Keyword so the same concept doesn't fragment into near-
    # duplicate spellings, and so keyword search/filter can do an exact tag
    # lookup instead of an icontains substring match on a joined string. See
    # Keyword's docstring above and articles/forms.py's TagifyKeywordsField.
    keyword_tags = models.ManyToManyField(Keyword, blank=True, related_name='articles')
    article_type = models.CharField(max_length=30, choices=ArticleType.choices)
    # A per-article editorial/business call, independent of article_type —
    # see ROADMAP.md Phase 7 "Business model (revised — three access tiers)".
    # No longer derived from article_type (that was a leftover academic-journal
    # assumption — a news article's monetization tier isn't implied by its category).
    access_type = models.CharField(
        max_length=20, choices=AccessType.choices, default=AccessType.OPEN_ACCESS,
        help_text='Free, subscriber-only, or a one-time-purchase "special" article.',
    )
    price = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text='One-time price, required only when access type is Pay-per-article.',
    )
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    is_pinned = models.BooleanField(
        default=False,
        help_text='Pin to the top of listings and the homepage, ahead of publication date. '
                   'If more than one article is pinned, the most recently published pinned one leads.',
    )
    homepage_section = models.CharField(
        max_length=20, choices=HomepageSection.choices, blank=True,
        help_text='Feature this article in a specific homepage section, regardless of its article '
                   'type. Leave blank to let that section auto-fill from recent articles of the '
                   'matching type instead — see articles/views.py HomeView.',
    )

    submission = models.OneToOneField(
        'submissions.Submission', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='article',
        help_text='Source submission this article was promoted from, if any.',
    )

    # Fully automatic, not editor-facing: created_at (below) already records
    # when the article was created, and publication_date is stamped by
    # save() the moment status becomes Published (see below) — no manual
    # submission/acceptance dates to track without an OJS integration.
    publication_date = models.DateField(null=True, blank=True)

    doi = models.CharField(max_length=100, unique=True, null=True, blank=True)
    pdf_file = models.FileField(
        upload_to='articles/%Y/%m/', null=True, blank=True,
        validators=[article_pdf_extension_validator, validate_article_pdf_size],
        help_text='PDF only, up to 100 MB.',
    )
    featured_image = models.ImageField(
        upload_to='articles/images/', null=True, blank=True,
        validators=[article_image_extension_validator, validate_featured_image_size],
        help_text='Hero/thumbnail image shown on the homepage, listing cards, and related-article links. '
                   'JPG or PNG, up to 10 MB.',
    )
    html_content = models.TextField(
        null=True, blank=True,
        help_text='Full-text body HTML, rendered as-is (trusted — admin/editor-authored only, '
                   'never end-user input). Shown only for open-access articles; subscription '
                   'articles stay gated behind the Phase 6 paywall regardless of this field.',
    )
    references = models.TextField(
        null=True, blank=True,
        help_text='Bibliography, one formatted citation per line. Rendered as a numbered list.',
    )

    authors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through='ArticleAuthor', related_name='authored_articles',
    )
    issue = models.ForeignKey(
        'issues.Issue', on_delete=models.SET_NULL, null=True, blank=True, related_name='articles',
        help_text='Optional story trail / issue this article belongs to.',
    )
    section = models.ForeignKey(
        'sections.Section', on_delete=models.SET_NULL, null=True, blank=True, related_name='articles',
        help_text='Optional subject-taxonomy placement (see the sections app) — independent of '
                   'article_type (format) and keyword_tags (free tags). Drives the public '
                   'primary-nav landing pages, not the homepage curation slots above.',
    )

    volume = models.CharField(max_length=10, null=True, blank=True)
    page_numbers = models.CharField(max_length=20, null=True, blank=True)
    citation_count = models.IntegerField(default=0)
    download_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def estimated_read_minutes(self):
        """Word count / 200wpm. Only counts html_content for open-access
        articles — a rough public-facing estimate, not viewer-aware (the
        actual paywall gate for subscription/pay-per-article tiers lives in
        billing.access.article_is_accessible, not here).
        """
        text = self.abstract or ''
        if self.access_type == self.AccessType.OPEN_ACCESS and self.html_content:
            text += ' ' + self.html_content
        return max(1, round(len(text.split()) / 200))

    def save(self, *args, **kwargs):
        # short_code first — a blank slug is built from it below, so it must
        # already exist by the time that runs. Applies regardless of how the
        # article was created (the editorial form, the pitches accept flow,
        # seed_demo_data, Django admin, ...) since every path ends up here.
        if not self.short_code:
            code = generate_short_code()
            while Article.objects.filter(short_code=code).exists():
                code = generate_short_code()
            self.short_code = code
        # Auto-slug from the title when an editor leaves it blank
        # (ArticleForm makes it optional) — the short_code suffix means two
        # articles with the same title can never collide, so there's no
        # uniqueness retry loop needed here the way _unique_article_slug
        # needs one elsewhere for slugs without a code suffix.
        if not self.slug:
            base = slugify(self.title) or 'article'
            self.slug = f'{base}-{self.short_code}'
        # publication_date is entirely automatic — stamped the moment status
        # becomes Published, never editor-facing. Doesn't re-stamp on a later
        # save (e.g. an edit to an already-published article).
        if self.status == self.Status.PUBLISHED and not self.publication_date:
            self.publication_date = timezone.localdate()
        super().save(*args, **kwargs)
        # Cheap and unconditional rather than trying to detect exactly which
        # field changes matter (status, homepage_section, is_pinned, or just
        # an edit to an already-featured article's title/image) — a save is
        # rare enough that clearing on every one isn't worth the complexity
        # of tracking which changes actually affect the homepage. See
        # articles/views.py HomeView.CACHE_KEY.
        cache.delete(HOME_SECTIONS_CACHE_KEY)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        # Required by django_comments_xtd (comment confirmation/moderation
        # redirects and email templates resolve content_object.get_absolute_url()
        # directly) — see ARCHITECTURE.md's comments section.
        return reverse('articles:article_detail', args=[self.slug])


class ArticleAuthor(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    order = models.IntegerField(default=0, help_text='Author ordering on the article byline.')
    is_corresponding = models.BooleanField(default=False)

    class Meta:
        ordering = ['order']
        unique_together = ('article', 'user')

    def __str__(self):
        return f'{self.user} on {self.article}'


class ArticleView(models.Model):
    """One page-view event — first-party, no third-party analytics vendor
    (August 2026 decision: buildable without an external account, unlike
    GA/Plausible/PostHog). Timestamped events, not just a running total on
    Article, so a real "trending this week" is possible, not just an
    all-time counter. See HomeView._build_sections (articles/views.py) for
    the trending query and ArticleDetailView for where these get recorded.
    """

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='page_views')
    session_key = models.CharField(
        max_length=40, blank=True,
        help_text='Django session key, used only to de-duplicate repeat views within a short window — no IP/fingerprinting.',
    )
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['article', 'viewed_at'])]

    def __str__(self):
        return f'View of {self.article} at {self.viewed_at}'
