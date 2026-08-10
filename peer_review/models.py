from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from submissions.models import Submission


class Review(models.Model):
    class Status(models.TextChoices):
        INVITED = 'invited', 'Invited'
        ACCEPTED = 'accepted', 'Accepted'
        DECLINED = 'declined', 'Declined'
        COMPLETED = 'completed', 'Completed'

    class Recommendation(models.TextChoices):
        ACCEPT = 'accept', 'Accept'
        MINOR_REVISION = 'minor_revision', 'Minor Revision'
        MAJOR_REVISION = 'major_revision', 'Major Revision'
        REJECT = 'reject', 'Reject'

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INVITED)
    invitation_date = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField(help_text='21 days from when the reviewer accepts the invitation.')
    completion_date = models.DateTimeField(null=True, blank=True)
    recommendation = models.CharField(
        max_length=30, choices=Recommendation.choices, null=True, blank=True,
    )
    comments_for_editor = models.TextField(null=True, blank=True)
    comments_for_author = models.TextField(null=True, blank=True)
    confidential_remarks = models.TextField(null=True, blank=True)

    score_overall = models.IntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    score_originality = models.IntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    score_methodology = models.IntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    score_significance = models.IntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )

    def __str__(self):
        return f'Review of {self.submission.title} by {self.reviewer}'
