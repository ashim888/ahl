from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from articles.seo import breadcrumb_list_structured_data
from billing import payments
from billing.models import Payment
from users.decorators import role_required
from users.models import User

from .forms import CourseModuleFormSet, TrainingCourseForm
from .models import Enrollment, TrainingCourse
from .seo import course_structured_data

# Single source of truth is User.EDITORIAL_ROLES (see users/models.py).
EDITORIAL_ROLES = User.EDITORIAL_ROLES


def _with_seat_counts(queryset):
    """Annotates active (non-cancelled) enrollment counts, used for "N
    learners" and seats-left on catalog cards without a query per card.
    """
    return queryset.annotate(
        active_enrollment_count=Count('enrollments', filter=~Q(enrollments__status=Enrollment.Status.CANCELLED)),
    )


class CourseListView(ListView):
    """Public course catalog — featured course on top, then a filterable
    grid (search, category, level, format), in the style of a MOOC catalog.
    """

    model = TrainingCourse
    template_name = 'training/course_list.html'
    context_object_name = 'courses'

    def get_queryset(self):
        queryset = _with_seat_counts(TrainingCourse.objects.filter(is_active=True))
        self.filters = {
            'q': self.request.GET.get('q', '').strip(),
            'category': self.request.GET.get('category', '').strip(),
            'level': self.request.GET.get('level', ''),
            'mode': self.request.GET.get('mode', ''),
        }
        if self.filters['q']:
            q = self.filters['q']
            queryset = queryset.filter(
                Q(title__icontains=q) | Q(subtitle__icontains=q) | Q(description__icontains=q)
                | Q(instructor__icontains=q) | Q(category__icontains=q),
            )
        if self.filters['category']:
            queryset = queryset.filter(category__iexact=self.filters['category'])
        if self.filters['level'] in TrainingCourse.Level.values:
            queryset = queryset.filter(level=self.filters['level'])
        if self.filters['mode'] in TrainingCourse.Mode.values:
            queryset = queryset.filter(mode=self.filters['mode'])
        return queryset.order_by('-is_featured', 'start_date', 'title')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active = TrainingCourse.objects.filter(is_active=True)
        is_filtered = any(self.filters.values())
        context['filters'] = self.filters
        context['is_filtered'] = is_filtered
        context['categories'] = sorted(
            {c for c in active.exclude(category='').values_list('category', flat=True)}, key=str.lower,
        )
        context['level_choices'] = TrainingCourse.Level.choices
        context['mode_choices'] = TrainingCourse.Mode.choices
        # Only on the unfiltered catalog — a filtered view is a search result, not a landing page.
        featured = None
        if not is_filtered:
            featured = _with_seat_counts(active.filter(is_featured=True)).order_by('start_date', 'title').first()
        context['featured_course'] = featured
        context['catalog_stats'] = {
            'courses': active.count(),
            'learners': Enrollment.objects.filter(course__is_active=True).exclude(
                status=Enrollment.Status.CANCELLED).values('user').distinct().count(),
            'instructors': active.values('instructor').distinct().count(),
        }
        context['meta_title'] = f'Training Programs — {settings.JOURNAL_NAME}'
        context['meta_description'] = f'Professional training programs offered by {settings.JOURNAL_NAME}.'
        return context


class CourseDetailView(DetailView):
    model = TrainingCourse
    template_name = 'training/course_detail.html'
    context_object_name = 'course'

    def get_queryset(self):
        return TrainingCourse.objects.filter(is_active=True).prefetch_related('modules')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.object
        enrolled_count = course.enrollments.exclude(status=Enrollment.Status.CANCELLED).count()
        context['enrolled_count'] = enrolled_count
        context['spots_left'] = (
            None if course.max_enrollments is None
            else max(course.max_enrollments - payments.seats_taken(course), 0)
        )
        if self.request.user.is_authenticated:
            context['enrollment'] = Enrollment.objects.filter(
                user=self.request.user, course=course,
            ).first()
        context['modules'] = list(course.modules.all())
        # Other courses, same category first.
        context['related_courses'] = list(
            _with_seat_counts(TrainingCourse.objects.filter(is_active=True).exclude(pk=course.pk)).annotate(
                other_category=Case(
                    When(category__iexact=course.category, then=0), default=1, output_field=IntegerField(),
                ) if course.category else Value(1, output_field=IntegerField()),
            ).order_by('other_category', '-is_featured', 'title')[:3],
        )
        context['meta_title'] = f'{course.title} — {settings.JOURNAL_NAME}'
        context['meta_description'] = (course.subtitle or course.description or '')[:200]
        image_url = self.request.build_absolute_uri(course.cover_image.url) if course.cover_image else None
        if image_url:
            context['meta_image_url'] = image_url
        context['structured_data_json'] = course_structured_data(
            course, journal_name=settings.JOURNAL_NAME, image_url=image_url,
        )
        context['breadcrumb_json'] = breadcrumb_list_structured_data([
            ('Home', self.request.build_absolute_uri(reverse('articles:home'))),
            ('Training Programs', self.request.build_absolute_uri(reverse('training:course_list'))),
            (course.title, None),
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

    # Seats held by people still paying count as taken (payments.seats_taken),
    # so the last seat can't be sold twice.
    if course.max_enrollments is not None and payments.seats_taken(course, exclude_user=request.user) >= course.max_enrollments:
        messages.error(request, 'This course is full.')
        return redirect('training:course_detail', pk=pk)

    # Fonepay's minimum is Rs. 1 — a free course enrolls directly.
    from billing.views import _buyer_pan, _pay_with_quote, checkout_promo

    quote, handled = checkout_promo(request, kind=Payment.Kind.COURSE, price=course.price, course=course)
    buyer_pan, pan_error = _buyer_pan(request) if request.method == 'POST' and not handled else ('', None)
    if handled:
        pass
    elif pan_error:
        messages.error(request, pan_error)
    elif request.method == 'POST' and course.price > 0:
        description = f'Training — {course.title}'
        result = _pay_with_quote(
            request, quote, kind=Payment.Kind.COURSE, description=description, course=course,
            success=reverse('training:course_detail', args=[pk]), buyer_pan=buyer_pan,
        )
        if isinstance(result, Payment):
            messages.success(request, f'Enrolled in "{course.title}".')
            return redirect('training:course_detail', pk=pk)
        if result is not None:
            return result
    elif request.method == 'POST' and course.price <= 0:
        # Free course: no payment, no receipt.
        if existing:
            existing.status = Enrollment.Status.ACTIVE
            existing.save(update_fields=['status'])
        else:
            Enrollment.objects.create(user=request.user, course=course, payment_status=Enrollment.PaymentStatus.PAID)
        messages.success(request, f'Enrolled in "{course.title}".')
        return redirect('training:course_detail', pk=pk)

    return render(request, 'training/course_checkout.html', {
        'course': course, 'quote': quote, 'buyer_pan': request.POST.get('buyer_pan') or payments.last_buyer_pan(request.user),
    })


# -- Editorial course management (CRUD, not public browsing) ---------------

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class CourseManageListView(ListView):
    """All courses regardless of active status, for editorial management."""

    model = TrainingCourse
    template_name = 'training/manage/course_list.html'
    context_object_name = 'courses'
    paginate_by = 30

    def get_queryset(self):
        queryset = TrainingCourse.objects.annotate(
            # distinct=True on all three: joining enrollments and modules in
            # one query would otherwise multiply each count by the other.
            enrollment_count=Count('enrollments', distinct=True),
            active_enrollment_count=Count(
                'enrollments', filter=~Q(enrollments__status=Enrollment.Status.CANCELLED), distinct=True,
            ),
            module_count=Count('modules', distinct=True),
        ).order_by('-created_at')
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
        active_enrollments = Enrollment.objects.exclude(status=Enrollment.Status.CANCELLED)
        context['summary'] = {
            'active_courses': TrainingCourse.objects.filter(is_active=True).count(),
            'enrollments': active_enrollments.count(),
            'paid': active_enrollments.filter(payment_status=Enrollment.PaymentStatus.PAID).count(),
            'featured': TrainingCourse.objects.filter(is_active=True, is_featured=True).count(),
        }
        context['selected_q'] = self.request.GET.get('q', '')
        return context


class CourseFormMixin:
    """Saves the course and its modules (CourseModuleFormSet) together — a
    course is only saved when both the form and every module row validate.
    """

    def get_success_url(self):
        return reverse('training:manage_course_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'module_formset' not in context:
            data = self.request.POST if self.request.method == 'POST' else None
            context['module_formset'] = CourseModuleFormSet(data, instance=self.object, prefix='modules')
        return context

    def form_valid(self, form):
        module_formset = CourseModuleFormSet(self.request.POST, instance=form.instance, prefix='modules')
        if not module_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form, module_formset=module_formset))
        self.object = form.save()
        module_formset.instance = self.object
        module_formset.save()
        messages.success(self.request, f'"{self.object.title}" {self.success_verb}.')
        return redirect(self.get_success_url())


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class CourseCreateView(CourseFormMixin, CreateView):
    model = TrainingCourse
    form_class = TrainingCourseForm
    template_name = 'training/manage/course_form.html'
    success_verb = 'created'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class CourseUpdateView(CourseFormMixin, UpdateView):
    model = TrainingCourse
    form_class = TrainingCourseForm
    template_name = 'training/manage/course_form.html'
    success_verb = 'updated'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context


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
    # Unfiltered totals for the course header card.
    counts = dict(course.enrollments.values_list('status').annotate(n=Count('id')))
    paid_count = course.enrollments.exclude(status=Enrollment.Status.CANCELLED).filter(
        payment_status=Enrollment.PaymentStatus.PAID,
    ).count()
    active_total = counts.get(Enrollment.Status.ACTIVE, 0) + counts.get(Enrollment.Status.COMPLETED, 0)
    course_summary = {
        'active': counts.get(Enrollment.Status.ACTIVE, 0),
        'completed': counts.get(Enrollment.Status.COMPLETED, 0),
        'cancelled': counts.get(Enrollment.Status.CANCELLED, 0),
        'paid': paid_count,
        'seats_taken': active_total,
        'seats_pct': min(100, round(active_total * 100 / course.max_enrollments)) if course.max_enrollments else None,
    }
    return render(request, 'training/manage/course_enrollments.html', {
        'course': course, 'course_summary': course_summary, 'enrollments': page_obj, 'page_obj': page_obj, 'is_paginated': page_obj.has_other_pages(),
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
