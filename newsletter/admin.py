from django.contrib import admin

from .models import NewsletterIssue, Subscriber


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ['email', 'status', 'user', 'subscribed_at', 'confirmed_at']
    list_filter = ['status']
    search_fields = ['email']


@admin.register(NewsletterIssue)
class NewsletterIssueAdmin(admin.ModelAdmin):
    list_display = ['subject', 'created_by', 'created_at', 'sent_at', 'recipient_count']
    search_fields = ['subject']
