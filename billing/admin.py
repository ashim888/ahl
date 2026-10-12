from django.contrib import admin

from .models import (
    ArticlePurchase, Organization, OrganizationMember, Payment, PlanFeature, SubscriptionPlan, UserSubscription,
)


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
    """The payment ledger — read-only: status comes from Fonepay, manual
    payments are recorded from the dashboard's grant/organization screens."""

    list_display = ['reference', 'receipt_number', 'user', 'organization', 'description', 'amount', 'status', 'created_at']
    list_filter = ['status', 'kind', 'gateway']
    search_fields = ['reference', 'receipt_number', 'user__email', 'organization__name', 'description', 'gateway_trace_id']
    readonly_fields = [f.name for f in Payment._meta.fields]


class OrganizationMemberInline(admin.TabularInline):
    model = OrganizationMember
    extra = 0
    readonly_fields = ['user', 'joined_at']
    can_delete = True


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'plan', 'start_date', 'end_date', 'seats', 'is_active']
    list_filter = ['is_active', 'plan']
    search_fields = ['name', 'email_domains', 'contact_email']
    inlines = [OrganizationMemberInline]
