from django.contrib import admin

from .models import ManuscriptFile, Submission


class ManuscriptFileInline(admin.TabularInline):
    model = ManuscriptFile
    extra = 0


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'submitter', 'editor_assigned', 'submission_date']
    list_filter = ['status', 'article_type']
    search_fields = ['title', 'abstract', 'keywords', 'submitter__email']
    inlines = [ManuscriptFileInline]
