from django.contrib import admin
from django.utils import timezone

from .models import ManuscriptFile, Submission


class ManuscriptFileInline(admin.TabularInline):
    model = ManuscriptFile
    extra = 0


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'submitter', 'editor_assigned', 'submission_date']
    list_select_related = ['submitter', 'editor_assigned']
    list_filter = ['status', 'article_type']
    search_fields = ['title', 'abstract', 'keywords', 'submitter__email']
    inlines = [ManuscriptFileInline]

    fieldsets = (
        ('Manuscript', {'fields': ('title', 'article_type', 'abstract', 'keywords', 'submitter', 'status')}),
        ('Author declarations', {'fields': ('cover_letter', 'suggested_reviewers', 'conflict_of_interest')}),
        ('Editorial screening', {'fields': ('editor_assigned', 'screening_notes', 'plagiarism_score')}),
        ('Decision', {'fields': ('decision', 'decision_date', 'revision_round')}),
    )

    actions = ['mark_under_screening', 'send_to_review', 'desk_reject']

    @admin.action(description='Mark as under screening')
    def mark_under_screening(self, request, queryset):
        updated = queryset.update(status=Submission.Status.UNDER_SCREENING)
        self.message_user(request, f'{updated} submission(s) marked under screening.')

    @admin.action(description='Screening passed → send to review')
    def send_to_review(self, request, queryset):
        updated = queryset.update(status=Submission.Status.UNDER_REVIEW)
        self.message_user(request, f'{updated} submission(s) sent to review.')

    @admin.action(description='Desk reject (screening failed)')
    def desk_reject(self, request, queryset):
        updated = queryset.update(
            status=Submission.Status.REJECTED, decision='desk_reject', decision_date=timezone.now(),
        )
        self.message_user(request, f'{updated} submission(s) desk rejected.')
