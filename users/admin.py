from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ['email']
    list_display = ['email', 'first_name', 'last_name', 'role', 'verification_status', 'is_verified', 'is_staff']
    list_filter = ['role', 'verification_status', 'is_verified', 'is_staff', 'is_active']
    search_fields = ['email', 'first_name', 'last_name', 'orcid', 'affiliation']

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name')}),
        ('Profile', {
            'fields': (
                'orcid', 'affiliation', 'department', 'bio', 'cv_file',
                'research_interests', 'linkedin_url', 'researchgate_url', 'publications',
            ),
        }),
        ('Role & verification', {'fields': ('role', 'is_verified', 'verification_status')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )

    actions = ['approve_verification', 'reject_verification']

    @admin.action(description='Approve verification (→ Verified Author)')
    def approve_verification(self, request, queryset):
        for user in queryset:
            user.verification_status = User.VerificationStatus.APPROVED
            user.is_verified = True
            user.role = User.Role.VERIFIED_AUTHOR
            user.save()
        self.message_user(request, f'{queryset.count()} user(s) approved.')

    @admin.action(description='Reject verification')
    def reject_verification(self, request, queryset):
        for user in queryset:
            user.verification_status = User.VerificationStatus.REJECTED
            user.is_verified = False
            user.save()
        self.message_user(request, f'{queryset.count()} user(s) rejected.')
