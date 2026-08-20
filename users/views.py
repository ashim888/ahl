from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView
from django.views.generic.detail import DetailView
from django_ratelimit.decorators import ratelimit

from articles.models import Article
from training.models import Enrollment

from .decorators import role_required
from .forms import (
    AuthorCreateForm, AuthorManageForm, ChangeRoleForm, GroupForm, ProfileUpdateForm,
    RegistrationForm, STAFF_ROLES, StaffCreateForm, StaffManageForm, UserGroupsForm,
)
from .models import User

# Single source of truth for both is User.EDITORIAL_ROLES / User.SENIOR_STAFF_ROLES
# (see users/models.py). Granting Editor/EiC/Admin is more sensitive than the
# Authors screen above — scoped to EiC/Admin only, not plain Editors.
EDITORIAL_ROLES = User.EDITORIAL_ROLES
STAFF_MANAGE_ROLES = User.SENIOR_STAFF_ROLES
# Raw Django Group/Permission config is more sensitive still — Admin only.
GROUP_MANAGE_ROLES = (User.Role.ADMIN,)


@method_decorator(ratelimit(key='ip', rate='10/h', method='POST', block=True), name='dispatch')
class RegisterView(CreateView):
    """Rate-limited by IP on POST only — viewing the form (GET) is unlimited,
    only repeated submit attempts count (bot/abuse mitigation, no CAPTCHA
    exists on this form yet — see ROADMAP.md Phase 9).
    """

    model = User
    form_class = RegistrationForm
    template_name = 'users/register.html'
    success_url = reverse_lazy('users:pending_verification')

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


@method_decorator(ratelimit(key='ip', rate='15/m', method='POST', block=True), name='dispatch')
class EmailLoginView(LoginView):
    """Rate-limited by IP on POST only — basic brute-force mitigation. No
    account-level lockout (django-axes) exists yet — see ROADMAP.md Phase 9.
    """

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


# Verifying users is an Editor-in-Chief/Admin capability (ARCHITECTURE.md §6.3) —
# deliberately not "is_staff", since Editors also have is_staff=True but aren't
# meant to approve/reject verifications themselves.
@role_required(User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)
def verification_queue(request):
    pending_users = User.objects.filter(
        verification_status=User.VerificationStatus.PENDING,
    ).order_by('date_joined')
    return render(request, 'users/verification_queue.html', {'pending_users': pending_users})


@role_required(User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)
def verification_detail(request, pk):
    """Full profile for one pending registration — the list view only shows
    a summary card, with no way to see bio/research_interests or anything
    else not already crammed into that card.
    """
    target = get_object_or_404(User, pk=pk, verification_status=User.VerificationStatus.PENDING)
    return render(request, 'users/verification_detail.html', {'target': target})


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


# -- Staff account management (Editor / Editor-in-Chief / Admin) -----------
# Editor-in-Chief and Admin only — granting editorial roles is more sensitive
# than the Authors screen above. See StaffFormMixin for the additional
# guardrail: an EiC can grant Editor/EiC but never mint a new Admin.

@method_decorator(role_required(*STAFF_MANAGE_ROLES), name='dispatch')
class StaffManageListView(ListView):
    model = User
    template_name = 'users/manage/staff_list.html'
    context_object_name = 'staff'
    paginate_by = 30

    def get_queryset(self):
        queryset = User.objects.filter(role__in=STAFF_ROLES).order_by('role', 'first_name')
        role = self.request.GET.get('role')
        if role:
            queryset = queryset.filter(role=role)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['role_choices'] = [(v, l) for v, l in User.Role.choices if v in STAFF_ROLES]
        context['selected_role'] = self.request.GET.get('role', '')
        return context


class StaffFormViewMixin:
    def get_success_url(self):
        return reverse('users:manage_staff_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['acting_user'] = self.request.user
        return kwargs


@method_decorator(role_required(*STAFF_MANAGE_ROLES), name='dispatch')
class StaffCreateView(StaffFormViewMixin, CreateView):
    model = User
    form_class = StaffCreateForm
    template_name = 'users/manage/staff_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.get_full_name()}" added as {form.instance.get_role_display()}.')
        return super().form_valid(form)


@method_decorator(role_required(*STAFF_MANAGE_ROLES), name='dispatch')
class StaffUpdateView(StaffFormViewMixin, UpdateView):
    form_class = StaffManageForm
    template_name = 'users/manage/staff_form.html'

    def get_queryset(self):
        return User.objects.filter(role__in=STAFF_ROLES)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.get_full_name()}" updated.')
        return super().form_valid(form)


@role_required(*STAFF_MANAGE_ROLES)
def staff_toggle_active(request, pk):
    """Reversible deactivate/reactivate, same pattern as author_toggle_active
    above — never hard-deletes the account."""
    if request.method != 'POST':
        raise PermissionDenied
    staff = get_object_or_404(User, pk=pk, role__in=STAFF_ROLES)
    if staff.pk == request.user.pk:
        messages.error(request, "You can't deactivate your own account.")
        return redirect('users:manage_staff_list')
    staff.is_active = not staff.is_active
    staff.save(update_fields=['is_active'])
    messages.success(request, f'{staff.email} {"reactivated" if staff.is_active else "deactivated"}.')
    return redirect('users:manage_staff_list')


@role_required(*STAFF_MANAGE_ROLES)
def change_role(request, pk):
    """The actual "set permissions" screen — moves a user to any Role,
    regardless of their current tier. Authors and Staff each only manage
    accounts already within their own tier (see ChangeRoleForm's docstring),
    so this is the one place that can promote a Verified Author to Editor,
    demote an Editor back down, etc.
    """
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "You can't change your own role — ask another Editor-in-Chief or Admin.")
        return redirect('users:manage_staff_list')

    if request.method == 'POST':
        form = ChangeRoleForm(request.POST, acting_user=request.user)
        if form.is_valid():
            new_role = form.cleaned_data['role']
            target.role = new_role
            # Any role above Unverified is, by definition, an approved
            # account — keep verification fields consistent with that
            # rather than leaving a stale pending/rejected state behind.
            if new_role == User.Role.UNVERIFIED:
                target.is_verified = False
                target.verification_status = User.VerificationStatus.PENDING
            else:
                target.is_verified = True
                target.verification_status = User.VerificationStatus.APPROVED
            target.save()
            messages.success(request, f'{target.get_full_name()} is now {target.get_role_display()}.')
            return redirect('users:manage_staff_list' if new_role in STAFF_ROLES else 'users:manage_author_list')
    else:
        form = ChangeRoleForm(initial={'role': target.role}, acting_user=request.user)

    return render(request, 'users/manage/change_role.html', {'form': form, 'target': target})


@method_decorator(role_required(*STAFF_MANAGE_ROLES), name='dispatch')
class PermissionsListView(ListView):
    """Every account, one role column, one Change Role action — the direct
    answer to "where do I set permissions", instead of having to already
    know whether someone's in the Authors or Staff tier first.
    """

    model = User
    template_name = 'users/manage/permissions_list.html'
    context_object_name = 'accounts'
    paginate_by = 50

    def get_queryset(self):
        queryset = User.objects.order_by('role', 'first_name')
        role = self.request.GET.get('role')
        if role:
            queryset = queryset.filter(role=role)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['role_choices'] = User.Role.choices
        context['selected_role'] = self.request.GET.get('role', '')
        return context


# -- Django Group/Permission management (Admin only) ------------------------
# See the note on GroupForm — this manages what a group *would* grant, ahead
# of anything in the app checking has_perm()/group membership yet.

@method_decorator(role_required(*GROUP_MANAGE_ROLES), name='dispatch')
class GroupManageListView(ListView):
    model = Group
    template_name = 'users/manage/group_list.html'
    context_object_name = 'groups'
    paginate_by = 30

    def get_queryset(self):
        return Group.objects.annotate(
            member_count=Count('user', distinct=True),
            permission_count=Count('permissions', distinct=True),
        ).order_by('name')


class GroupFormMixin:
    def get_success_url(self):
        return reverse('users:manage_group_list')


@method_decorator(role_required(*GROUP_MANAGE_ROLES), name='dispatch')
class GroupCreateView(GroupFormMixin, CreateView):
    model = Group
    form_class = GroupForm
    template_name = 'users/manage/group_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, f'Group "{form.instance.name}" created.')
        return super().form_valid(form)


@method_decorator(role_required(*GROUP_MANAGE_ROLES), name='dispatch')
class GroupUpdateView(GroupFormMixin, UpdateView):
    model = Group
    form_class = GroupForm
    template_name = 'users/manage/group_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'Group "{form.instance.name}" updated.')
        return super().form_valid(form)


@method_decorator(role_required(*GROUP_MANAGE_ROLES), name='dispatch')
class GroupDeleteView(DeleteView):
    model = Group
    template_name = 'users/manage/group_confirm_delete.html'
    success_url = reverse_lazy('users:manage_group_list')

    def form_valid(self, form):
        messages.success(self.request, f'Group "{self.object.name}" deleted.')
        return super().form_valid(form)


@role_required(*GROUP_MANAGE_ROLES)
def manage_user_groups(request, pk):
    target = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = UserGroupsForm(request.POST)
        if form.is_valid():
            target.groups.set(form.cleaned_data['groups'])
            messages.success(request, f"{target.get_full_name()}'s groups updated.")
            return redirect('users:manage_permissions_list')
    else:
        form = UserGroupsForm(initial={'groups': target.groups.all()})
    return render(request, 'users/manage/user_groups.html', {'form': form, 'target': target})
