from django.contrib import admin

from .models import AdEvent, AdSettings, AdSlot


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


@admin.register(AdSettings)
class AdSettingsAdmin(admin.ModelAdmin):
    # Singleton — always exactly one row (AdSettings.get_solo()). The
    # /manage/ads/ toggle button is the normal way to flip this; admin
    # registration is just a superuser fallback, same as any other model.
    list_display = ['placeholder_zones', 'updated_at']
