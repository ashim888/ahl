from django.contrib import admin

from .models import GlossaryTerm, Resource


@admin.register(GlossaryTerm)
class GlossaryTermAdmin(admin.ModelAdmin):
    list_display = ('term_ne', 'term_en', 'is_published', 'updated_at')
    list_filter = ('is_published',)
    search_fields = ('term_ne', 'term_en', 'also_called', 'definition_ne', 'definition_en')
    filter_horizontal = ('keyword_tags', 'related_terms')


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ('title', 'resource_type', 'source', 'year', 'language', 'is_published', 'download_count')
    list_filter = ('resource_type', 'language', 'is_published')
    search_fields = ('title', 'summary', 'source')
    autocomplete_fields = ('related_articles',)
    filter_horizontal = ('keyword_tags',)
    readonly_fields = ('download_count', 'file_size', 'created_at', 'updated_at')
