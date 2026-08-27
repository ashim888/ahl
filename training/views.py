from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from articles.seo import breadcrumb_list_structured_data
from billing.gateway import get_gateway
from users.decorators import role_required
from users.models import User

from .forms import TrainingCourseForm
from .models import Enrollment, TrainingCourse
from .seo import course_structured_data

# Single source of truth is User.EDITORIAL_ROLES (see users/models.py).
EDITORIAL_ROLES = User.EDITORIAL_ROLES


class CourseListView(ListView):
    model = TrainingCourse
    template_name = 'training/course_list.html'
    context_object_name = 'courses'

    def get_queryset(self):
        return TrainingCourse.objects.filter(is_active=True).order_by('title')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meta_title'] = f'Training Programs — {settings.JOURNAL_NAME}'
        context['meta_description'] = f'Professional training programs offered by {settings.JOURNAL_NAME}.'
        return context


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
        context['meta_title'] = f'{self.object.title} — {settings.JOURNAL_NAME}'
        context['meta_description'] = (self.object.description or '')[:200]
        context['structured_data_json'] = course_structured_data(self.object, journal_name=settings.JOURNAL_NAME)
        context['breadcrumb_json'] = breadcrumb_list_structured_data([
            ('Home', self.request.build_absolute_uri(reverse('articles:home'))),
            ('Training Programs', self.request.build_absolute_uri(reverse('training:course_list'))),
            (self.object.title, None),
        ])
        return context


@login_required
def course_checkout(request, pk):
    """Self-serve enroll-and-pay. No real gateway is wired in yet
    (billing.gateway.StubGateway always succeeds) — see ROADMAP.md Phase 7.
    """
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

    if request.method == 'POST':
        result = get_gateway().charge(request.user, course.price, f'Training — {course.title}')
        if result.success:
            if existing:
                existing.status = Enrollment.Status.ACTIVE
                existing.payment_status = Enrollment.PaymentStatus.PAID
                existing.payment_reference = result.reference
                existing.save(update_fields=['status', 'payment_status', 'payment_reference'])
            else:
                Enrollment.objects.create(
                    user=request.user, course=course,
                    payment_status=Enrollment.PaymentStatus.PAID, payment_reference=result.reference,
                )
            messages.success(request, f'Enrolled in "{course.title}".')
            return redirect('training:course_detail', pk=pk)
        messages.error(request, result.error or 'Payment failed — please try again.')

    return render(request, 'training/course_checkout.html', {'course': course})


# -- Editorial course management (CRUD, not public browsing) ---------------

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class CourseManageListView(ListView):
    """All courses regardless of active status, for editorial management."""

    model = TrainingCourse
    template_name = 'training/manage/course_list.html'
    context_object_name = 'courses'
    paginate_by = 30

    def get_queryset(self):
        queryset = TrainingCourse.objects.annotate(enrollment_count=Count('enrollments')).order_by('-created_at')
        active = self.request.GET.get('active')
        q = self.request.GET.get('q')
        if active == 'yes':
            queryset = queryset.filter(is_active=True)
        elif active == 'no':
            queryset = queryset.filter(is_active=False)
        if q:
            queryset = queryset.filter(Q(title__icontains=q) | Q(instructor__icontains=q))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['selected_active'] = self.request.GET.get('active', '')
        context['selected_q'] = self.request.GET.get('q', '')
        return context


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
    status = request.GET.get('status')
    payment_status = request.GET.get('payment_status')
    if status in Enrollment.Status.values:
        enrollments = enrollments.filter(status=status)
    if payment_status in Enrollment.PaymentStatus.values:
        enrollments = enrollments.filter(payment_status=payment_status)
    # A plain function view (not a ListView), so pagination is manual —
    # a popular course's enrollment list can run into the hundreds, and
    # this previously rendered every row with no pagination at all.
    page_obj = Paginator(enrollments, 30).get_page(request.GET.get('page'))
    return render(request, 'training/manage/course_enrollments.html', {
        'course': course, 'enrollments': page_obj, 'page_obj': page_obj, 'is_paginated': page_obj.has_other_pages(),
        'status_choices': Enrollment.Status.choices,
        'payment_status_choices': Enrollment.PaymentStatus.choices,
        'selected_status': status or '',
        'selected_payment_status': payment_status or '',
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


@role_required(*EDITORIAL_ROLES)
@require_POST
def enrollment_bulk_update(request, pk):
    """Same status/payment_status edit as enrollment_update, applied to
    every checked row at once — previously only a one-<select>-per-row
    inline edit, no way to update a batch of enrollments together.
    Scoped to this course (via the pks queryset filter) so a crafted pks
    list can't touch another course's enrollments.
    """
    course = get_object_or_404(TrainingCourse, pk=pk)
    status = request.POST.get('status')
    payment_status = request.POST.get('payment_status')
    pks = request.POST.getlist('pks')

    update_fields = []
    if status in Enrollment.Status.values:
        update_fields.append('status')
    if payment_status in Enrollment.PaymentStatus.values:
        update_fields.append('payment_status')

    updated_count = 0
    if update_fields:
        enrollments = Enrollment.objects.filter(pk__in=pks, course=course)
        for enrollment in enrollments:
            if 'status' in update_fields:
                enrollment.status = status
            if 'payment_status' in update_fields:
                enrollment.payment_status = payment_status
            enrollment.save(update_fields=update_fields)
            updated_count += 1

    if updated_count:
        messages.success(request, f'{updated_count} enrollment(s) updated.')
    else:
        messages.error(request, 'No eligible enrollments were selected.')
    return redirect('training:manage_course_enrollments', pk=course.pk)
