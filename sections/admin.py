from django.contrib import admin
from modeltranslation.admin import TranslationAdmin

from .models import Section


@admin.register(Section)
class SectionAdmin(TranslationAdmin):
    list_display = ['name', 'parent', 'order', 'is_active', 'link_url_name']
    list_filter = ['is_active', 'parent']
    search_fields = ['name_en', 'name_ne', 'slug']
    prepopulated_fields = {'slug': ('name_en',)}
