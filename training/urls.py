from django.urls import path

from . import views

app_name = 'training'

urlpatterns = [
    path('training/', views.CourseListView.as_view(), name='course_list'),
    path('training/<int:pk>/', views.CourseDetailView.as_view(), name='course_detail'),
    path('training/<int:pk>/checkout/', views.course_checkout, name='course_checkout'),

    # Editorial CRUD — Editor/EiC/Admin only (see EDITORIAL_ROLES in views.py)
    path('manage/training/', views.CourseManageListView.as_view(), name='manage_course_list'),
    path('manage/training/new/', views.CourseCreateView.as_view(), name='manage_course_create'),
    path('manage/training/<int:pk>/edit/', views.CourseUpdateView.as_view(), name='manage_course_update'),
    path('manage/training/<int:pk>/delete/', views.CourseDeleteView.as_view(), name='manage_course_delete'),
    path('manage/training/<int:pk>/enrollments/', views.course_enrollments, name='manage_course_enrollments'),
    path(
        'manage/training/<int:pk>/enrollments/bulk-update/', views.enrollment_bulk_update,
        name='manage_enrollment_bulk_update',
    ),
    path('manage/enrollments/<int:pk>/update/', views.enrollment_update, name='manage_enrollment_update'),
]
