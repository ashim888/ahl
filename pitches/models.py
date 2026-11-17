from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


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
        SUBMITTED = 'submitted', _('Submitted')
        IN_REVIEW = 'in_review', _('In Review')
        ACCEPTED = 'accepted', _('Accepted')
        REJECTED = 'rejected', _('Rejected')
        PUBLISHED = 'published', _('Published')

    class Kind(models.TextChoices):
        STORY = 'story', _('Story pitch')
        # A health claim a reader wants checked (/pitches/claim/, from the
        # fact-checks page). Accepting one opens a Fact check draft.
        CLAIM = 'claim', _('Claim to check')

    title = models.CharField(max_length=500)
    summary = models.TextField(help_text='The pitch itself — what the story is and why it matters now.')
    body = models.TextField(
        blank=True, help_text='Optional draft text, if you already have one. Not required to submit a pitch.',
    )
    # Nullable (August 2026 — submission opened to anyone, no account
    # required): set automatically when submitted while logged in; null for
    # an anonymous pitch, which carries its own contact info in
    # submitter_name/submitter_email instead. Use the contact_name/
    # contact_email properties below rather than reading these fields
    # directly, so callers don't have to branch on which case applies.
    submitter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='story_pitches',
    )
    submitter_name = models.CharField(
        max_length=255, blank=True, help_text='Only used for an anonymous (not logged in) pitch.',
    )
    submitter_email = models.EmailField(
        blank=True, help_text='Only used for an anonymous (not logged in) pitch — how to follow up with them.',
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.STORY)
    claim_url = models.URLField(
        _('Link to the claim'), max_length=500, blank=True,
        help_text=_('Optional: where you saw it (a post, video or article).'),
    )
    # The student research track (/pitches/new/?track=student): students and
    # early-career researchers turning their own research into a story.
    is_student = models.BooleanField(
        _('I am a student or early-career researcher'), default=False,
        help_text=_('Tick this if the pitch is about your own research (a thesis, a project, a paper). '
                    'An editor will help you turn it into a story for the public.'),
    )
    institution = models.CharField(
        _('Your college, university or institution'), max_length=255, blank=True,
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

    @property
    def is_claim(self):
        return self.kind == self.Kind.CLAIM

    @property
    def noun(self):
        """For the (English) emails: "story pitch" or "claim"."""
        return 'claim' if self.is_claim else 'story pitch'

    @property
    def contact_name(self):
        return self.submitter.get_full_name() if self.submitter else self.submitter_name

    @property
    def contact_email(self):
        return self.submitter.email if self.submitter else self.submitter_email
