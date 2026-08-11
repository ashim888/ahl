from django.contrib import admin

from .models import EditorialBoardMember


@admin.register(EditorialBoardMember)
class EditorialBoardMemberAdmin(admin.ModelAdmin):
    list_display = ['name', 'role_title', 'affiliation', 'order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'role_title', 'affiliation']
