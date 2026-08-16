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

    path('pending-verification/', views.pending_verification_view, name='pending_verification'),
    path('pending-verification/reapply/', views.reapply_verification, name='reapply_verification'),

    path('verification-queue/', views.verification_queue, name='verification_queue'),
    path('verification-queue/<int:pk>/', views.verification_detail, name='verification_detail'),
    path(
        'verification-queue/<int:pk>/<str:decision>/',
        views.verification_decide, name='verification_decide',
    ),

    path('manage/authors/', views.AuthorManageListView.as_view(), name='manage_author_list'),
    path('manage/authors/new/', views.AuthorCreateView.as_view(), name='manage_author_create'),
    path('manage/authors/<int:pk>/edit/', views.AuthorUpdateView.as_view(), name='manage_author_update'),
    path('manage/authors/<int:pk>/toggle-active/', views.author_toggle_active, name='manage_author_toggle_active'),

    path('manage/staff/', views.StaffManageListView.as_view(), name='manage_staff_list'),
    path('manage/staff/new/', views.StaffCreateView.as_view(), name='manage_staff_create'),
    path('manage/staff/<int:pk>/edit/', views.StaffUpdateView.as_view(), name='manage_staff_update'),
    path('manage/staff/<int:pk>/toggle-active/', views.staff_toggle_active, name='manage_staff_toggle_active'),

    path('manage/permissions/', views.PermissionsListView.as_view(), name='manage_permissions_list'),
    # The actual permission-setting screen — see ChangeRoleForm's docstring
    # for why this exists separately from the Authors/Staff screens above.
    path('manage/users/<int:pk>/change-role/', views.change_role, name='change_role'),

    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(template_name='users/password_reset_form.html'),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(template_name='users/password_reset_done.html'),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(template_name='users/password_reset_confirm.html'),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(template_name='users/password_reset_complete.html'),
        name='password_reset_complete',
    ),
]
