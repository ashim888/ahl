import logging

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
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView
from django.views.generic.detail import DetailView
from django_ratelimit.decorators import ratelimit

from articles.models import Article, Author, Bookmark, KeywordFollow
from billing.institutions import pending_organization_for
from billing.models import ArticleGift
from pitches.models import StoryPitch
from sections.models import Section
from training.models import Enrollment

from .decorators import role_required
from .forms import (
    AccountCreateForm, AccountManageForm, ChangeRoleForm, GroupForm, ProfileUpdateForm,
    RegistrationForm, STAFF_ROLES, StaffCreateForm, StaffManageForm, UserGroupsForm,
)
from . import email_confirmation
from .invites import send_account_invite
from .models import User

# Single source of truth for both is User.EDITORIAL_ROLES / User.SENIOR_STAFF_ROLES
# (see users/models.py). Granting Editor/EiC/Admin is more sensitive than the
# Authors screen above — scoped to EiC/Admin only, not plain Editors.
logger = logging.getLogger(__name__)

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
    def get_success_url(self):
        """Back to where the reader was (e.g. a paywalled article or a
        checkout, via ?next=), otherwise the homepage."""
        target = self.request.POST.get('next') or self.request.GET.get('next')
        if target and url_has_allowed_host_and_scheme(
            target, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure(),
        ):
            return target
        return reverse('articles:home')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next'] = self.request.GET.get('next', '')
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _('Welcome, %(name)s — your account is ready.') % {'name': self.object.first_name})
        # Explicit backend required since AUTHENTICATION_BACKENDS has more
        # than one entry (axes.backends.AxesStandaloneBackend +
        # ModelBackend, see settings.py §9.6) — login() can only infer the
        # backend automatically when exactly one is configured, and this
        # call never goes through authenticate() (there's no password check
        # here, the account was just created) so nothing else sets it.
        # AxesStandaloneBackend itself never authenticates a user — it only
        # blocks locked-out attempts — so ModelBackend is the real one.
        login(self.request, self.object, backend='django.contrib.auth.backends.ModelBackend')
        # Signed up with an address at a subscribing organization: send the
        # confirmation link straight away, it's what unlocks their access.
        organization = pending_organization_for(self.object)
        if organization:
            email_confirmation.send_confirmation(self.object, organization)
            messages.info(self.request, _(
                '%(org)s has a subscription. We’ve emailed you a link — confirm your address to read with it.',
            ) % {'org': organization.name})
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

    def form_valid(self, form):
        # The link came by email (a reset or an account invite), so the
        # person has just proved they receive mail at this address.
        email_confirmation.confirm(form.user)
        return super().form_valid(form)


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
        from billing.access import current_subscription
        from billing.institutions import organization_for
        from billing.services import paid_through

        context['billing_subscription'] = current_subscription(self.request.user)
        context['billing_paid_through'] = paid_through(self.request.user)
        context['billing_organization'] = (
            None if context['billing_subscription'] else organization_for(self.request.user)
        )
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
    """Ask to be verified (first time), or re-apply after a rejection's
    cooldown. The EiC/Admin reviewers are emailed (users/signals.py)."""
    user = request.user
    if request.method == 'POST' and user.can_request_verification:
        first_time = user.verification_status == User.VerificationStatus.NOT_REQUESTED
        # Plain save() (no update_fields) so the pre_save signal's
        # verification_status_changed_at stamp is actually persisted.
        user.verification_status = User.VerificationStatus.PENDING
        user.save()
        messages.success(request, 'Your verification request has been sent to the editors.' if first_time
                         else 'Your verification request has been resubmitted.')
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['acting_user'] = self.request.user
        return kwargs

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


def _staff_manageable_by(user):
    """Staff accounts `user` may edit or deactivate. An Editor-in-Chief
    manages Editors and other EiCs but never an Admin: editing an Admin's
    email and then resetting its password would hand over the Admin
    account. Only an Admin manages Admins."""
    queryset = User.objects.filter(role__in=STAFF_ROLES)
    if user.role != User.Role.ADMIN:
        queryset = queryset.exclude(role=User.Role.ADMIN)
    return queryset


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
        return _staff_manageable_by(self.request.user)

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
    staff = get_object_or_404(_staff_manageable_by(request.user), pk=pk)
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
    if target.role == User.Role.ADMIN and request.user.role != User.Role.ADMIN:
        raise PermissionDenied
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
                target.verification_status = User.VerificationStatus.NOT_REQUESTED
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


@login_required
@require_POST
@ratelimit(key='user', rate='3/h', method='POST', block=False)
def send_email_confirmation(request):
    """Emails the signed-in reader a link proving they own their address."""
    if getattr(request, 'limited', False):
        messages.error(request, _('We’ve sent a few links already — check your inbox (and spam), or try again in an hour.'))
    elif request.user.email_confirmed_at:
        messages.info(request, _('Your email address is already confirmed.'))
    elif email_confirmation.send_confirmation(request.user, pending_organization_for(request.user)):
        messages.success(request, _('We’ve emailed a confirmation link to %(email)s.') % {'email': request.user.email})
    else:
        messages.error(request, _('We couldn’t send the email just now. Please try again in a few minutes.'))
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('billing:account')
    return redirect(next_url)


def confirm_email(request, token):
    """The emailed link. Works signed in or not — the token names the account."""
    user = email_confirmation.user_for_token(token)
    if user is None:
        return render(request, 'users/confirm_email_invalid.html', status=400)
    email_confirmation.confirm(user)
    from billing.institutions import organization_for

    organization = organization_for(user)
    if organization:
        messages.success(request, _('Email confirmed — you now read with %(org)s’s subscription.') % {'org': organization.name})
    else:
        messages.success(request, _('Email confirmed. Thank you!'))
    return redirect('billing:account' if request.user.is_authenticated else 'users:login')


# -- Privacy & data (users/privacy.py) ---------------------------------------

@login_required
def privacy_settings(request):
    """/account/privacy/ — email preferences, data download, cookie choice
    and account deletion, in one place."""
    from newsletter.models import Subscriber

    user = request.user
    if request.method == 'POST' and request.POST.get('action') == 'emails':
        user.email_topic_digest = bool(request.POST.get('email_topic_digest'))
        user.email_renewal_reminders = bool(request.POST.get('email_renewal_reminders'))
        user.save(update_fields=['email_topic_digest', 'email_renewal_reminders'])
        messages.success(request, _('Email preferences saved.'))
        return redirect('users:privacy')
    newsletter = Subscriber.objects.filter(email__iexact=user.email).first()
    return render(request, 'users/privacy.html', {
        'newsletter': newsletter,
        'newsletter_confirmed': bool(newsletter and newsletter.status == Subscriber.Status.CONFIRMED),
        'can_self_delete': not (user.is_editorial_staff or user.is_superuser),
    })


@login_required
@ratelimit(key='user', rate='5/h', block=False)
def privacy_export(request):
    """Downloads everything linked to the account as JSON."""
    import json

    from django.http import HttpResponse

    from . import privacy

    if getattr(request, 'limited', False):
        messages.error(request, _('You’ve downloaded your data several times this hour — please try again later.'))
        return redirect('users:privacy')
    data = json.dumps(privacy.export_user_data(request.user), ensure_ascii=False, indent=2, default=str)
    response = HttpResponse(data, content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="my-data-{timezone.localdate():%Y-%m-%d}.json"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_POST
@ratelimit(key='user', rate='5/h', method='POST', block=True)
def privacy_delete_account(request):
    """Self-service account deletion — needs the password (or, for an
    account that never set one, typing the email address)."""
    from django.contrib.auth import logout

    from . import privacy

    user = request.user
    password = request.POST.get('password', '')
    confirmed = (
        user.check_password(password) if user.has_usable_password()
        else request.POST.get('email_confirm', '').strip().lower() == user.email.lower()
    )
    if not request.POST.get('understood') or not confirmed:
        messages.error(request, _('Your account was not deleted: confirm with your password and tick the box.'))
        return redirect(f"{reverse('users:privacy')}#delete")
    try:
        privacy.erase_user(user, remove_comments=bool(request.POST.get('remove_comments')))
    except privacy.ErasureRefused as exc:
        messages.error(request, str(exc))
        return redirect('users:privacy')
    logout(request)
    return render(request, 'users/account_deleted.html')


@csrf_exempt  # one-click unsubscribe (RFC 8058) POSTs from mail clients, no session
def email_unsubscribe(request, token):
    """Unsubscribe link in the topic digest and renewal reminder emails.
    GET shows a confirm button (mail scanners open links); POST — the
    button, or a mail client's one-click — switches the email off."""
    from . import privacy

    user, kind = privacy.read_unsubscribe_token(token)
    if user is None:
        return render(request, 'users/email_unsubscribe.html', {'invalid': True}, status=400)
    field, label = privacy.EMAIL_KINDS[kind]
    done = False
    if request.method == 'POST':
        setattr(user, field, False)
        user.save(update_fields=[field])
        done = True
    return render(request, 'users/email_unsubscribe.html', {'label': label, 'done': done, 'token': token})


@role_required(*User.SENIOR_STAFF_ROLES)
@require_POST
def account_erase(request, pk):
    """Staff acting on a deletion request received by email or letter."""
    from . import privacy

    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        raise PermissionDenied
    if request.POST.get('confirm_email', '').strip().lower() != target.email.lower():
        messages.error(request, 'Not deleted — type the account’s email address exactly to confirm.')
        return redirect('users:manage_account_update', pk=target.pk)
    email = target.email
    try:
        privacy.erase_user(target, remove_comments=bool(request.POST.get('remove_comments')))
    except privacy.ErasureRefused as exc:
        messages.error(request, str(exc))
        return redirect('users:manage_account_update', pk=target.pk)
    logger.info('Account %s (%s) erased by %s on request', target.pk, email, request.user.email)
    messages.success(request, f'Personal data of {email} deleted. Receipts and published records were kept, anonymised.')
    return redirect('users:manage_account_list')
