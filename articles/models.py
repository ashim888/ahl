from django.conf import settings
from django.db import models
from django.utils import timezone

from .validators import (
    article_image_extension_validator, article_pdf_extension_validator,
    validate_article_pdf_size, validate_featured_image_size,
)


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

    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500, unique=True)
    abstract = models.TextField()
    keywords = models.CharField(max_length=500, null=True, blank=True)
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
        # publication_date is entirely automatic — stamped the moment status
        # becomes Published, never editor-facing. Doesn't re-stamp on a later
        # save (e.g. an edit to an already-published article).
        if self.status == self.Status.PUBLISHED and not self.publication_date:
            self.publication_date = timezone.localdate()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


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
