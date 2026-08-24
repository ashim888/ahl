from django.contrib import admin

from .models import AdEvent, AdSlot


@admin.register(AdSlot)
class AdSlotAdmin(admin.ModelAdmin):
    list_display = ['sponsor_name', 'zone', 'is_active', 'start_date', 'end_date', 'impression_count', 'click_count']
    list_filter = ['zone', 'is_active']
    search_fields = ['sponsor_name']


@admin.register(AdEvent)
class AdEventAdmin(admin.ModelAdmin):
    list_display = ['ad_slot', 'event_type', 'occurred_at']
    list_filter = ['event_type']
    date_hierarchy = 'occurred_at'
