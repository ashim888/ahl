from django.conf import settings
from django.db import models

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
        OPEN_ACCESS = 'open_access', 'Open Access'
        SUBSCRIPTION = 'subscription', 'Subscription'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        ARCHIVED = 'archived', 'Archived'

    # Default access model per article type (editor can override afterward —
    # e.g. an author pays the APC to make a normally-subscription article OA).
    ACCESS_TYPE_DEFAULTS = {
        ArticleType.ORIGINAL_RESEARCH: AccessType.SUBSCRIPTION,
        ArticleType.REVIEW_ARTICLE: AccessType.SUBSCRIPTION,
        ArticleType.METHODOLOGY_PAPER: AccessType.SUBSCRIPTION,
        ArticleType.CASE_REPORT: AccessType.OPEN_ACCESS,
        ArticleType.SHORT_COMMUNICATION: AccessType.OPEN_ACCESS,
        ArticleType.EDITORIAL: AccessType.OPEN_ACCESS,
        ArticleType.NEWS_COMMENTARY: AccessType.OPEN_ACCESS,
        ArticleType.LETTER_TO_EDITOR: AccessType.OPEN_ACCESS,
    }

    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500, unique=True)
    abstract = models.TextField()
    keywords = models.CharField(max_length=500, null=True, blank=True)
    article_type = models.CharField(max_length=30, choices=ArticleType.choices)
    access_type = models.CharField(
        max_length=20, choices=AccessType.choices, blank=True,
        help_text='Leave blank to default from article_type on creation; editors may override.',
    )
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)

    submission = models.OneToOneField(
        'submissions.Submission', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='article',
        help_text='Source submission this article was promoted from, if any.',
    )

    submission_date = models.DateField(null=True, blank=True)
    acceptance_date = models.DateField(null=True, blank=True)
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
    )

    volume = models.CharField(max_length=10, null=True, blank=True)
    page_numbers = models.CharField(max_length=20, null=True, blank=True)
    citation_count = models.IntegerField(default=0)
    download_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def resolve_access_type(cls, article_type, access_type):
        """Shared by save() and the unsaved preview view (articles/views.py)
        so both apply the exact same default-resolution rule.
        """
        return access_type or cls.ACCESS_TYPE_DEFAULTS.get(article_type, cls.AccessType.SUBSCRIPTION)

    @property
    def estimated_read_minutes(self):
        """Word count / 200wpm, based on whichever body text is actually
        public (full text if open access, otherwise just the abstract).
        """
        text = self.abstract or ''
        if self.access_type == self.AccessType.OPEN_ACCESS and self.html_content:
            text += ' ' + self.html_content
        return max(1, round(len(text.split()) / 200))

    def save(self, *args, **kwargs):
        self.access_type = self.resolve_access_type(self.article_type, self.access_type)
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
