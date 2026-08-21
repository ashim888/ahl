from django.conf import settings
from django.db import models


class StoryPitch(models.Model):
    """A reader/author's lightweight pitch for a news story — deliberately
    NOT a revival of the dormant `submissions` app's academic manuscript
    model (no scoring, no revision rounds, no plagiarism check, no required
    file upload — see ROADMAP.md Phase 8 for why that's a different app on
    purpose). Accepting a pitch promotes it into a real `Article` (still a
    Draft — editorial staff finish/format it there, same as any other
    article), linked back via `article` for provenance.
    """

    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'Submitted'
        IN_REVIEW = 'in_review', 'In Review'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'
        PUBLISHED = 'published', 'Published'

    title = models.CharField(max_length=500)
    summary = models.TextField(help_text='The pitch itself — what the story is and why it matters now.')
    body = models.TextField(
        blank=True, help_text='Optional draft text, if you already have one. Not required to submit a pitch.',
    )
    submitter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='story_pitches',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    editor_feedback = models.TextField(
        blank=True, help_text='Shown to the submitter — reason for the decision or requested changes.',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    article = models.OneToOneField(
        'articles.Article', on_delete=models.SET_NULL, null=True, blank=True, related_name='source_pitch',
        help_text='Set when accepted and promoted into a real Article.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.get_status_display()})'
