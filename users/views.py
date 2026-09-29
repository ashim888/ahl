from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, PasswordResetConfirmView, PasswordResetView
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView
from django.views.generic.detail import DetailView
from django_ratelimit.decorators import ratelimit

from articles.models import Article, Author, Bookmark, KeywordFollow
from billing.models import ArticleGift
from pitches.models import StoryPitch
from sections.models import Section
from training.models import Enrollment

from .decorators import role_required
from .forms import (
    AccountCreateForm, AccountManageForm, ChangeRoleForm, GroupForm, ProfileUpdateForm,
    RegistrationForm, STAFF_ROLES, StaffCreateForm, StaffManageForm, UserGroupsForm,
)
from .invites import send_account_invite
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
        # Explicit backend required since AUTHENTICATION_BACKENDS has more
        # than one entry (axes.backends.AxesStandaloneBackend +
        # ModelBackend, see settings.py §9.6) — login() can only infer the
        # backend automatically when exactly one is configured, and this
        # call never goes through authenticate() (there's no password check
        # here, the account was just created) so nothing else sets it.
        # AxesStandaloneBackend itself never authenticates a user — it only
        # blocks locked-out attempts — so ModelBackend is the real one.
        login(self.request, self.object, backend='django.contrib.auth.backends.ModelBackend')
        return response


@method_decorator(ratelimit(key='ip', rate='15/m', method='POST', block=True), name='dispatch')
class EmailLoginView(LoginView):
    """Rate-limited by IP on POST only — basic brute-force mitigation. No
    account-level lockout (django-axes) exists yet — see ROADMAP.md Phase 9.
    """

    template_name = 'users/login.html'
    redirect_authenticated_user = True


@method_decorator(ratelimit(key='ip', rate='5/h', method='POST', block=True), name='dispatch')
class RateLimitedPasswordResetView(PasswordResetView):
    """Rate-limited by IP on POST only — every other public form-POST
    endpoint in this app already has this (login, registration, comments,
    pitches, newsletter signup); the reset request form was the one gap,
    and it's a real one: unthrottled, it's both an email-enumeration probe
    (a reset email only sends for an address that exists) and a flood
    vector against a real inbox.
    """

    template_name = 'users/password_reset_form.html'
    # Django's own default (`reverse_lazy('password_reset_done')`, no
    # namespace) 404s here — users/urls.py is included with app_name='users',
    # so every URL name in it only resolves under the 'users:' namespace.
    # Pre-existing bug, not introduced by this rate limiting — a real
    # submission of the un-rate-limited stock view would have crashed with
    # NoReverseMatch too; caught while adding this class's own tests.
    success_url = reverse_lazy('users:password_reset_done')
    # Branded HTML part (templates/email/base.html layout); the plain-text
    # part stays Django's default registration/password_reset_email.html.
    html_email_template_name = 'registration/password_reset_email_html.html'


@method_decorator(ratelimit(key='ip', rate='10/h', method='POST', block=True), name='dispatch')
class RateLimitedPasswordResetConfirmView(PasswordResetConfirmView):
    """Rate-limited by IP on POST only — the token in the URL is already
    hard to guess, but an unthrottled confirm endpoint still lets an
    attacker brute-force it at whatever rate they like. Slightly looser
    than the request form above since a legitimate user can genuinely need
    a couple of attempts here (password confirmation mismatch, validator
    rejection).
    """

    template_name = 'users/password_reset_confirm.html'
    # Same namespace fix as RateLimitedPasswordResetView.success_url above —
    # the stock default reverses an unnamespaced 'password_reset_complete'.
    success_url = reverse_lazy('users:password_reset_complete')


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
        # Any authenticated account can submit a pitch (see
        # pitches.views.PitchCreateView) — this page itself is
        # login_required, so no further role check is needed here.
        context['story_pitches'] = StoryPitch.objects.filter(
            submitter=self.request.user,
        ).order_by('-created_at')[:5]
        context['followed_sections'] = Section.objects.filter(
            followers__user=self.request.user,
        ).order_by('name')
        context['saved_articles'] = Bookmark.objects.filter(
            user=self.request.user,
        ).select_related('article')[:5]
        context['followed_keywords'] = KeywordFollow.objects.filter(
            user=self.request.user,
        ).select_related('keyword')
        context['active_gifts'] = ArticleGift.objects.filter(
            gifter=self.request.user, expires_at__gte=timezone.now(),
        ).select_related('article')
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
@method_decorator(role_required(User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN), name='dispatch')
class VerificationQueueView(ListView):
    """Was a plain, unpaginated function view — the one queue in the
    workspace with no pagination at all, unlike every structurally
    identical one (pitches, articles, ads, training, staff). A registration
    spike would have rendered the entire pending list on one page.
    """

    model = User
    template_name = 'users/verification_queue.html'
    context_object_name = 'pending_users'
    paginate_by = 30

    def get_queryset(self):
        return User.objects.filter(
            verification_status=User.VerificationStatus.PENDING,
        ).order_by('date_joined')


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


@role_required(User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)
@require_POST
def verification_bulk_decide(request):
    """Same decision logic as verification_decide, applied to every checked
    row at once — a registration spike previously meant clicking Approve/
    Reject one account at a time with a full page reload each.
    """
    decision = request.POST.get('decision')
    if decision not in ('approve', 'reject'):
        raise PermissionDenied

    pks = request.POST.getlist('pks')
    applied_count = 0
    for target in User.objects.filter(pk__in=pks):
        applied = target.approve_verification() if decision == 'approve' else target.reject_verification()
        if applied:
            applied_count += 1

    if applied_count:
        messages.success(request, f'{applied_count} user(s) {decision}d.')
    else:
        messages.error(request, 'No eligible users were selected.')
    return redirect('users:verification_queue')


# -- Editorial account management (login accounts, not bylines) -----------
# Scoped to User.VERIFICATION_QUEUE_ROLES (unverified, verified_author) —
# reader and author *login* accounts. Public byline profiles are
# articles.Author (see articles/author_views.py, /manage/authors/): an author
# needs no account, and gets one here only when they need to log in.
# Editor/EiC/Admin accounts are managed under Staff below.

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AccountManageListView(ListView):
    model = User
    template_name = 'users/manage/account_list.html'
    context_object_name = 'accounts'
    paginate_by = 30

    def get_queryset(self):
        queryset = User.objects.filter(
            role__in=User.VERIFICATION_QUEUE_ROLES,
        ).select_related('author_profile').order_by('-date_joined')
        role = self.request.GET.get('role')
        q = self.request.GET.get('q')
        if role:
            queryset = queryset.filter(role=role)
        if q:
            queryset = queryset.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) | Q(affiliation__icontains=q),
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['selected_q'] = self.request.GET.get('q', '')
        context['role_choices'] = [
            (value, label) for value, label in User.Role.choices if value in User.VERIFICATION_QUEUE_ROLES
        ]
        context['selected_role'] = self.request.GET.get('role', '')
        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AccountCreateView(CreateView):
    """New login account. With ?author=<pk> it's the "Create user account"
    action for an Author profile: the form is prefilled from the author and
    the new account is linked to it on save.
    """

    model = User
    form_class = AccountCreateForm
    template_name = 'users/manage/account_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.author = None
        author_pk = request.GET.get('author') or request.POST.get('author')
        if author_pk:
            self.author = get_object_or_404(Author, pk=author_pk)
            if self.author.user_id:
                messages.info(request, f'"{self.author.name}" already has an account ({self.author.user.email}).')
                return redirect('articles:manage_author_update', pk=self.author.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if self.author:
            first, _, last = self.author.name.rpartition(' ')
            initial.update({'first_name': first or last, 'last_name': last if first else '', 'email': self.author.email})
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        context['author'] = self.author
        return context

    def form_valid(self, form):
        user = form.save()
        self.object = user
        if self.author:
            self.author.user = user
            if not self.author.email:
                self.author.email = user.email
            self.author.save(update_fields=['user', 'email'])
        if form.sends_invite:
            sent = send_account_invite(user, invited_by=self.request.user)
            if sent:
                messages.success(self.request, f'Account created for {user.email} — they\'ve been emailed a link to set their password.')
            else:
                messages.warning(
                    self.request,
                    f'Account created for {user.email}, but the invitation email could not be sent. '
                    'Ask them to use "Forgot password" on the login page.',
                )
        else:
            messages.success(self.request, f'Account created for {user.email}.')
        if self.author:
            return redirect('articles:manage_author_list')
        return redirect('users:manage_account_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AccountUpdateView(UpdateView):
    form_class = AccountManageForm
    template_name = 'users/manage/account_form.html'

    def get_queryset(self):
        return User.objects.filter(role__in=User.VERIFICATION_QUEUE_ROLES)

    def get_success_url(self):
        return reverse('users:manage_account_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.get_full_name()}" updated.')
        return super().form_valid(form)


@role_required(*EDITORIAL_ROLES)
def account_toggle_active(request, pk):
    """Reversible deactivate/reactivate — the "delete" action for this screen.
    Never hard-deletes the User row. Bylines are unaffected either way: they
    point at the Author profile, not the login.
    """
    if request.method != 'POST':
        raise PermissionDenied
    account = get_object_or_404(User, pk=pk, role__in=User.VERIFICATION_QUEUE_ROLES)
    account.is_active = not account.is_active
    account.save(update_fields=['is_active'])
    messages.success(request, f'{account.email} {"reactivated" if account.is_active else "deactivated"}.')
    return redirect('users:manage_account_list')


@role_required(*EDITORIAL_ROLES)
@require_POST
def account_resend_invite(request, pk):
    """Re-sends the set-your-password email — only for accounts that still
    have no usable password (an invite that expired or went missing)."""
    account = get_object_or_404(User, pk=pk, role__in=User.VERIFICATION_QUEUE_ROLES)
    if account.has_usable_password():
        messages.info(request, f'{account.email} has already set a password.')
    elif send_account_invite(account, invited_by=request.user):
        messages.success(request, f'Invitation re-sent to {account.email}.')
    else:
        messages.error(request, f'The invitation email to {account.email} could not be sent.')
    return redirect('users:manage_account_list')


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
        # Newest-joined first — role-based grouping is still available via
        # the Role filter above, so this doesn't lose that, just stops
        # defaulting to it.
        queryset = User.objects.filter(role__in=STAFF_ROLES).order_by('-date_joined')
        role = self.request.GET.get('role')
        q = self.request.GET.get('q')
        if role:
            queryset = queryset.filter(role=role)
        if q:
            queryset = queryset.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['role_choices'] = [(v, l) for v, l in User.Role.choices if v in STAFF_ROLES]
        context['selected_role'] = self.request.GET.get('role', '')
        context['selected_q'] = self.request.GET.get('q', '')
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
        response = super().form_valid(form)
        form.apply_publish_permission(self.object)
        return response


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
        response = super().form_valid(form)
        form.apply_publish_permission(self.object)
        return response


@role_required(*STAFF_MANAGE_ROLES)
def staff_toggle_active(request, pk):
    """Reversible deactivate/reactivate, same pattern as account_toggle_active
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
            return redirect('users:manage_staff_list' if new_role in STAFF_ROLES else 'users:manage_account_list')
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
        queryset = User.objects.order_by('-date_joined')
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
        # Django's built-in auth.Group has no created_at field — -id is the
        # closest available proxy for "most recently created" on MySQL,
        # where ids are assigned in insertion order.
        return Group.objects.annotate(
            member_count=Count('user', distinct=True),
            permission_count=Count('permissions', distinct=True),
        ).order_by('-id')


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
