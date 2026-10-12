from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ContentReport(models.Model):
    """A reader telling us something is wrong with an article or a comment —
    abuse, health misinformation, a copyright claim, someone's private
    information, spam, or a factual error. Sent from the "Report" links on
    article pages and under each comment (/report/); handled by editors in
    the dashboard (/editorial/reports/). Keeps a record of every notice and
    what was done about it — the takedown trail a publisher should be able
    to show.
    """

    class Reason(models.TextChoices):
        ERROR = 'error', _('A factual error that needs correcting')
        MISINFORMATION = 'misinformation', _('Misleading or dangerous health information')
        ABUSE = 'abuse', _('Abusive, hateful or harassing')
        PRIVACY = 'privacy', _('Shares someone’s private or health information')
        COPYRIGHT = 'copyright', _('Uses my copyrighted work without permission')
        SPAM = 'spam', _('Spam or advertising')
        OTHER = 'other', _('Something else')

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        RESOLVED = 'resolved', 'Action taken'
        DISMISSED = 'dismissed', 'No action needed'

    article = models.ForeignKey(
        'articles.Article', on_delete=models.SET_NULL, null=True, blank=True, related_name='reports',
    )
    comment = models.ForeignKey(
        'django_comments_xtd.XtdComment', on_delete=models.SET_NULL, null=True, blank=True, related_name='reports',
    )
    # What was reported, as text — survives the article/comment being deleted.
    target_summary = models.CharField(max_length=300)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    details = models.TextField(max_length=3000, blank=True)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='content_reports',
    )
    reporter_name = models.CharField(max_length=150, blank=True)
    reporter_email = models.EmailField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    resolution_note = models.TextField(blank=True, help_text='What was done — kept as the record of this notice.')
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_reason_display()}: {self.target_summary}'

    @property
    def target_url(self) -> str:
        if self.comment_id and self.comment:
            return f'{self.comment.content_object.get_absolute_url()}#c{self.comment_id}' if self.comment.content_object else ''
        return self.article.get_absolute_url() if self.article_id and self.article else ''
