from django.contrib import admin

from .models import StoryPitch


@admin.register(StoryPitch)
class StoryPitchAdmin(admin.ModelAdmin):
    list_display = ['title', 'contact_name', 'contact_email', 'status', 'reviewed_by', 'created_at']
    list_filter = ['status']
    search_fields = ['title', 'submitter__email', 'submitter_email']
