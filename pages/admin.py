from django.contrib import admin

from .models import SitePage


@admin.register(SitePage)
class SitePageAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'is_published', 'updated_at']
    readonly_fields = ['updated_at', 'updated_by']
