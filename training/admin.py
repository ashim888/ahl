from django.contrib import admin

from .models import Enrollment, TrainingCourse


@admin.register(TrainingCourse)
class TrainingCourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'instructor', 'price', 'duration', 'is_active', 'max_enrollments']
    list_filter = ['is_active']
    search_fields = ['title', 'instructor', 'description']


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ['user', 'course', 'status', 'payment_status', 'enrolled_at']
    list_filter = ['status', 'payment_status']
    search_fields = ['user__email', 'course__title']
