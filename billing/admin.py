from django.contrib import admin

from .models import ArticlePurchase, SubscriptionPlan, UserSubscription


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'plan_type', 'price', 'duration_days', 'is_active']
    list_filter = ['plan_type', 'is_active']
    search_fields = ['name']


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'plan', 'status', 'start_date', 'end_date']
    list_select_related = ['user', 'plan']
    list_filter = ['status', 'plan']
    search_fields = ['user__email']


@admin.register(ArticlePurchase)
class ArticlePurchaseAdmin(admin.ModelAdmin):
    list_display = ['user', 'article', 'amount', 'purchased_at']
    list_select_related = ['user', 'article']
    search_fields = ['user__email', 'article__title']
