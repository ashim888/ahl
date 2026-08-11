from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, ListView, TemplateView, UpdateView
from django.views.generic.detail import DetailView

from articles.models import Article
from training.models import Enrollment

from .decorators import role_required
from .forms import AuthorCreateForm, AuthorManageForm, ProfileUpdateForm, RegistrationForm
from .models import User

# Matches EDITORIAL_ROLES in articles/views.py, admin_custom/views.py, editorial_board/views.py, training/views.py.
EDITORIAL_ROLES = (User.Role.EDITOR, User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)


class RegisterView(CreateView):
    model = User
    form_class = RegistrationForm
    template_name = 'users/register.html'
    success_url = reverse_lazy('users:pending_verification')

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class EmailLoginView(LoginView):
    template_name = 'users/login.html'
    redirect_authenticated_user = True


class ProfileView(DetailView):
    model = User
    template_name = 'users/profile.html'
    context_object_name = 'profile_user'

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['enrollments'] = Enrollment.objects.filter(
            user=self.request.user,
        ).select_related('course').order_by('-enrolled_at')
        return context


class ProfileUpdateView(UpdateView):
    model = User
    form_class = ProfileUpdateForm
    template_name = 'users/profile_edit.html'
    success_url = reverse_lazy('users:profile')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, 'Profile updated.')
        return super().form_valid(form)


profile_view = login_required(ProfileView.as_view())
profile_update_view = login_required(ProfileUpdateView.as_view())


class PendingVerificationView(TemplateView):
    template_name = 'users/pending_verification.html'


pending_verification_view = login_required(PendingVerificationView.as_view())


@login_required
def reapply_verification(request):
    user = request.user
    if request.method == 'POST' and user.can_reapply:
        # Plain save() (no update_fields) so the pre_save signal's
        # verification_status_changed_at stamp is actually persisted.
        user.verification_status = User.VerificationStatus.PENDING
        user.save()
        messages.success(request, 'Your verification request has been resubmitted.')
    return redirect('users:pending_verification')


# Verifying users is an Editor-in-Chief/Admin capability (ARCHITECTURE.md §6.2) —
# deliberately not "is_staff", since Editors also have is_staff=True but aren't
# meant to approve/reject verifications themselves.
@role_required(User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)
def verification_queue(request):
    pending_users = User.objects.filter(
        verification_status=User.VerificationStatus.PENDING,
    ).order_by('date_joined')
    return render(request, 'users/verification_queue.html', {'pending_users': pending_users})


@role_required(User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)
def verification_decide(request, pk, decision):
    if decision not in ('approve', 'reject') or request.method != 'POST':
        raise PermissionDenied

    target = get_object_or_404(User, pk=pk)
    applied = target.approve_verification() if decision == 'approve' else target.reject_verification()
    if applied:
        messages.success(request, f'{target.email} {decision}d.')
    else:
        messages.error(
            request,
            f'{target.email} has role "{target.get_role_display()}", which the verification '
            'queue does not manage — no change made.',
        )
    return redirect('users:verification_queue')


# -- Editorial author management (CRUD, not public browsing) ---------------
# Scoped to User.VERIFICATION_QUEUE_ROLES (unverified, verified_author) — the
# same "author-tier" accounts the verification queue governs. Editor/EiC/Admin
# accounts are managed via Django admin, not this screen.

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AuthorManageListView(ListView):
    model = User
    template_name = 'users/manage/author_list.html'
    context_object_name = 'authors'
    paginate_by = 30

    def get_queryset(self):
        queryset = User.objects.filter(
            role__in=User.VERIFICATION_QUEUE_ROLES,
        ).annotate(
            published_article_count=Count(
                'authored_articles', filter=Q(authored_articles__status=Article.Status.PUBLISHED), distinct=True,
            ),
        ).order_by('-date_joined')
        role = self.request.GET.get('role')
        if role:
            queryset = queryset.filter(role=role)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['role_choices'] = [
            (value, label) for value, label in User.Role.choices if value in User.VERIFICATION_QUEUE_ROLES
        ]
        context['selected_role'] = self.request.GET.get('role', '')
        return context


class AuthorFormMixin:
    def get_success_url(self):
        return reverse('users:manage_author_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AuthorCreateView(AuthorFormMixin, CreateView):
    model = User
    form_class = AuthorCreateForm
    template_name = 'users/manage/author_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.get_full_name()}" added as a verified author.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AuthorUpdateView(AuthorFormMixin, UpdateView):
    form_class = AuthorManageForm
    template_name = 'users/manage/author_form.html'

    def get_queryset(self):
        return User.objects.filter(role__in=User.VERIFICATION_QUEUE_ROLES)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.get_full_name()}" updated.')
        return super().form_valid(form)


@role_required(*EDITORIAL_ROLES)
def author_toggle_active(request, pk):
    """Reversible deactivate/reactivate — the "delete" action for this screen.
    Never hard-deletes the User row, which would cascade through their
    authorship links on any articles they've written.
    """
    if request.method != 'POST':
        raise PermissionDenied
    author = get_object_or_404(User, pk=pk, role__in=User.VERIFICATION_QUEUE_ROLES)
    author.is_active = not author.is_active
    author.save(update_fields=['is_active'])
    messages.success(request, f'{author.email} {"reactivated" if author.is_active else "deactivated"}.')
    return redirect('users:manage_author_list')
