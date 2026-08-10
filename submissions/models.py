from django.conf import settings
from django.db import models

from articles.models import Article

from .validators import manuscript_extension_validator, validate_manuscript_file_size


class Submission(models.Model):
    """Working record for a manuscript from upload through editorial decision.

    Independent of Article: an accepted Submission is promoted to an Article
    by copying its metadata (see Article.submission for the audit link back).
    """

    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'Submitted'
        UNDER_SCREENING = 'under_screening', 'Under Screening'
        UNDER_REVIEW = 'under_review', 'Under Review'
        MINOR_REVISION = 'minor_revision', 'Minor Revision'
        MAJOR_REVISION = 'major_revision', 'Major Revision'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'
        IN_PRODUCTION = 'in_production', 'In Production'
        PUBLISHED = 'published', 'Published'

    title = models.CharField(max_length=500)
    article_type = models.CharField(max_length=30, choices=Article.ArticleType.choices)
    abstract = models.TextField()
    keywords = models.CharField(max_length=500, null=True, blank=True)

    submitter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submissions',
    )
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.SUBMITTED)
    submission_date = models.DateTimeField(auto_now_add=True)

    editor_assigned = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_submissions',
    )
    screening_notes = models.TextField(null=True, blank=True)
    plagiarism_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    decision = models.CharField(max_length=30, null=True, blank=True)
    decision_date = models.DateTimeField(null=True, blank=True)
    revision_round = models.IntegerField(default=0)
    cover_letter = models.TextField(null=True, blank=True)
    suggested_reviewers = models.TextField(null=True, blank=True)
    conflict_of_interest = models.TextField(null=True, blank=True)

    def __str__(self):
        return f'{self.title} ({self.get_status_display()})'


class ManuscriptFile(models.Model):
    class FileType(models.TextChoices):
        PDF = 'pdf', 'PDF'
        WORD = 'word', 'Word'

    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name='manuscript_files',
    )
    file = models.FileField(
        upload_to='manuscripts/%Y/%m/',
        validators=[manuscript_extension_validator, validate_manuscript_file_size],
        help_text='PDF, DOC, or DOCX, up to 50 MB.',
    )
    file_type = models.CharField(max_length=10, choices=FileType.choices)
    version = models.IntegerField(default=1)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']

    def __str__(self):
        return f'{self.submission.title} v{self.version} ({self.file_type})'
