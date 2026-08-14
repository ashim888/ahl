from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import TrainingCourseForm
from .models import Enrollment, TrainingCourse

# Matches EDITORIAL_ROLES in articles/views.py, admin_custom/views.py, editorial_board/views.py.
EDITORIAL_ROLES = (User.Role.EDITOR, User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)


class CourseListView(ListView):
    model = TrainingCourse
    template_name = 'training/course_list.html'
    context_object_name = 'courses'

    def get_queryset(self):
        return TrainingCourse.objects.filter(is_active=True).order_by('title')


class CourseDetailView(DetailView):
    model = TrainingCourse
    template_name = 'training/course_detail.html'
    context_object_name = 'course'

    def get_queryset(self):
        return TrainingCourse.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        enrolled_count = self.object.enrollments.exclude(status=Enrollment.Status.CANCELLED).count()
        context['enrolled_count'] = enrolled_count
        context['spots_left'] = (
            None if self.object.max_enrollments is None
            else max(self.object.max_enrollments - enrolled_count, 0)
        )
        if self.request.user.is_authenticated:
            context['enrollment'] = Enrollment.objects.filter(
                user=self.request.user, course=self.object,
            ).first()
        return context


@login_required
@require_POST
def enroll(request, pk):
    course = get_object_or_404(TrainingCourse, pk=pk, is_active=True)
    existing = Enrollment.objects.filter(user=request.user, course=course).first()

    if existing and existing.status != Enrollment.Status.CANCELLED:
        messages.info(request, "You're already enrolled in this course.")
        return redirect('training:course_detail', pk=pk)

    if course.max_enrollments is not None:
        active_count = course.enrollments.exclude(status=Enrollment.Status.CANCELLED).count()
        if active_count >= course.max_enrollments:
            messages.error(request, 'This course is full.')
            return redirect('training:course_detail', pk=pk)

    if existing:
        existing.status = Enrollment.Status.ACTIVE
        existing.save()
    else:
        Enrollment.objects.create(user=request.user, course=course)

    messages.success(request, f'Enrolled in "{course.title}". Payment is tracked as pending until Phase 7\'s payment integration lands.')
    return redirect('training:course_detail', pk=pk)


# -- Editorial course management (CRUD, not public browsing) ---------------

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class CourseManageListView(ListView):
    """All courses regardless of active status, for editorial management."""

    model = TrainingCourse
    template_name = 'training/manage/course_list.html'
    context_object_name = 'courses'
    paginate_by = 30

    def get_queryset(self):
        return TrainingCourse.objects.annotate(enrollment_count=Count('enrollments')).order_by('-created_at')


class CourseFormMixin:
    def get_success_url(self):
        return reverse('training:manage_course_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class CourseCreateView(CourseFormMixin, CreateView):
    model = TrainingCourse
    form_class = TrainingCourseForm
    template_name = 'training/manage/course_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.title}" created.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class CourseUpdateView(CourseFormMixin, UpdateView):
    model = TrainingCourse
    form_class = TrainingCourseForm
    template_name = 'training/manage/course_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.title}" updated.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class CourseDeleteView(DeleteView):
    model = TrainingCourse
    template_name = 'training/manage/course_confirm_delete.html'
    success_url = reverse_lazy('training:manage_course_list')

    def form_valid(self, form):
        messages.success(self.request, f'"{self.object.title}" deleted.')
        return super().form_valid(form)


@role_required(*EDITORIAL_ROLES)
def course_enrollments(request, pk):
    course = get_object_or_404(TrainingCourse, pk=pk)
    enrollments = course.enrollments.select_related('user').order_by('-enrolled_at')
    return render(request, 'training/manage/course_enrollments.html', {
        'course': course, 'enrollments': enrollments,
        'status_choices': Enrollment.Status.choices,
        'payment_status_choices': Enrollment.PaymentStatus.choices,
    })


@role_required(*EDITORIAL_ROLES)
@require_POST
def enrollment_update(request, pk):
    """Quick inline edit from the enrollments list — status/payment_status
    only (matches Django admin's EnrollmentAdmin, minus the bulk actions).
    """
    enrollment = get_object_or_404(Enrollment, pk=pk)
    status = request.POST.get('status')
    payment_status = request.POST.get('payment_status')
    if status in Enrollment.Status.values:
        enrollment.status = status
    if payment_status in Enrollment.PaymentStatus.values:
        enrollment.payment_status = payment_status
    enrollment.save(update_fields=['status', 'payment_status'])
    messages.success(request, f'Enrollment for {enrollment.user.email} updated.')
    return redirect('training:manage_course_enrollments', pk=enrollment.course_id)
