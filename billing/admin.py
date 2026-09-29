from django.contrib import admin

from .models import ArticlePurchase, Payment, PlanFeature, SubscriptionPlan, UserSubscription


@admin.register(PlanFeature)
class PlanFeatureAdmin(admin.ModelAdmin):
    list_display = ['label', 'order']
    ordering = ['order', 'id']


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'plan_type', 'price', 'duration_days', 'is_featured', 'is_active']
    list_filter = ['plan_type', 'is_active']
    search_fields = ['name']
    filter_horizontal = ['features']


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


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Fonepay checkouts — read-mostly: status comes from Fonepay, not staff edits."""

    list_display = ['reference', 'user', 'description', 'amount', 'status', 'created_at', 'completed_at']
    list_filter = ['status', 'kind', 'gateway']
    search_fields = ['reference', 'user__email', 'description', 'gateway_trace_id']
    readonly_fields = [f.name for f in Payment._meta.fields]
