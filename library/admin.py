from django.contrib import admin

from .models import Resource


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ('title', 'resource_type', 'source', 'year', 'language', 'is_published', 'download_count')
    list_filter = ('resource_type', 'language', 'is_published')
    search_fields = ('title', 'summary', 'source')
    autocomplete_fields = ('related_articles',)
    filter_horizontal = ('keyword_tags',)
    readonly_fields = ('download_count', 'file_size', 'created_at', 'updated_at')
