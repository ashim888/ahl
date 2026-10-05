from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'users'

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.EmailLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_update_view, name='profile_edit'),
    path('account/confirm-email/', views.send_email_confirmation, name='send_email_confirmation'),
    path('account/privacy/', views.privacy_settings, name='privacy'),
    path('account/privacy/download/', views.privacy_export, name='privacy_export'),
    path('account/privacy/delete/', views.privacy_delete_account, name='privacy_delete'),
    path('email/unsubscribe/<str:token>/', views.email_unsubscribe, name='email_unsubscribe'),
    path('manage/accounts/<int:pk>/erase/', views.account_erase, name='manage_account_erase'),
    path('account/confirm-email/<str:token>/', views.confirm_email, name='confirm_email'),

    path('pending-verification/', views.pending_verification_view, name='pending_verification'),
    path('pending-verification/reapply/', views.reapply_verification, name='reapply_verification'),

    path('verification-queue/', views.VerificationQueueView.as_view(), name='verification_queue'),
    path('verification-queue/bulk-decide/', views.verification_bulk_decide, name='verification_bulk_decide'),
    path('verification-queue/<int:pk>/', views.verification_detail, name='verification_detail'),
    path(
        'verification-queue/<int:pk>/<str:decision>/',
        views.verification_decide, name='verification_decide',
    ),

    # Reader/author *login* accounts. Byline profiles (no account needed)
    # live at /manage/authors/ in the articles app.
    path('manage/accounts/', views.AccountManageListView.as_view(), name='manage_account_list'),
    path('manage/accounts/new/', views.AccountCreateView.as_view(), name='manage_account_create'),
    path('manage/accounts/<int:pk>/edit/', views.AccountUpdateView.as_view(), name='manage_account_update'),
    path('manage/accounts/<int:pk>/toggle-active/', views.account_toggle_active, name='manage_account_toggle_active'),
    path('manage/accounts/<int:pk>/resend-invite/', views.account_resend_invite, name='manage_account_resend_invite'),

    path('manage/staff/', views.StaffManageListView.as_view(), name='manage_staff_list'),
    path('manage/staff/new/', views.StaffCreateView.as_view(), name='manage_staff_create'),
    path('manage/staff/<int:pk>/edit/', views.StaffUpdateView.as_view(), name='manage_staff_update'),
    path('manage/staff/<int:pk>/toggle-active/', views.staff_toggle_active, name='manage_staff_toggle_active'),

    path('manage/permissions/', views.PermissionsListView.as_view(), name='manage_permissions_list'),
    # The actual permission-setting screen — see ChangeRoleForm's docstring
    # for why this exists separately from the Authors/Staff screens above.
    path('manage/users/<int:pk>/change-role/', views.change_role, name='change_role'),
    path('manage/users/<int:pk>/groups/', views.manage_user_groups, name='manage_user_groups'),

    # Django Group/Permission config (Admin only) — see GroupForm's docstring.
    path('manage/groups/', views.GroupManageListView.as_view(), name='manage_group_list'),
    path('manage/groups/new/', views.GroupCreateView.as_view(), name='manage_group_create'),
    path('manage/groups/<int:pk>/edit/', views.GroupUpdateView.as_view(), name='manage_group_update'),
    path('manage/groups/<int:pk>/delete/', views.GroupDeleteView.as_view(), name='manage_group_delete'),

    path(
        'password-reset/',
        views.RateLimitedPasswordResetView.as_view(),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(template_name='users/password_reset_done.html'),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        views.RateLimitedPasswordResetConfirmView.as_view(),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(template_name='users/password_reset_complete.html'),
        name='password_reset_complete',
    ),
]
