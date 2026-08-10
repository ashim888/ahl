from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['submission', 'reviewer', 'status', 'due_date', 'recommendation']
    list_filter = ['status', 'recommendation']
    search_fields = ['submission__title', 'reviewer__email']
