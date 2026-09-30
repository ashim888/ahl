from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, Permission
from django.forms import ModelForm

from ajna_health_lens.forms import apply_tailwind_widgets
from .models import User


class RegistrationForm(UserCreationForm):
    """Reader self-registration: name, email and password only. A news
    reader signs up to subscribe, buy, comment or enroll, so the old
    journal-era profile fields (ORCID, CV, affiliation, publications...)
    aren't asked for here; they remain optional on /profile/edit/.
    Creates role=unverified (the model default).
    """

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('first_name', 'last_name', 'email'):
            self.fields[name].required = True
        self.fields['first_name'].widget.attrs['autocomplete'] = 'given-name'
        self.fields['last_name'].widget.attrs['autocomplete'] = 'family-name'
        self.fields['email'].widget.attrs['autocomplete'] = 'email'
        apply_tailwind_widgets(self)


class ProfileUpdateForm(ModelForm):
    """Editable profile fields. Deliberately excludes email/role/verification_status —
    those are admin-controlled, not self-service.
    """

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name',
            'orcid', 'affiliation', 'department', 'bio', 'photo', 'cv_file',
            'research_interests', 'linkedin_url', 'researchgate_url', 'publications',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind_widgets(self, skip=('cv_file', 'file', 'photo'))


# Fields shared by the editorial account create/update forms below
# (/manage/accounts/ — reader and author login accounts; public byline
# profiles are articles.Author, managed separately under /manage/authors/).
# Deliberately excludes role/verification_status/is_verified on edit —
# those stay owned by the verification queue (users/views.py
# verification_decide) so there's one place that keeps them in sync.
ACCOUNT_PROFILE_FIELDS = [
    'first_name', 'last_name', 'email',
    'orcid', 'affiliation', 'department', 'bio', 'photo', 'cv_file',
    'research_interests', 'linkedin_url', 'researchgate_url', 'publications',
    'is_active',
]


class AccountManageForm(ModelForm):
    """Editorial edit of an existing reader/author account — content fields
    plus is_active as a reversible deactivate/reactivate toggle (not a hard
    delete of the account).
    """

    class Meta:
        model = User
        fields = ACCOUNT_PROFILE_FIELDS

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # The login email is Editor-in-Chief/Admin only: changing someone's
        # email and then requesting a password reset takes over the account
        # (a paying subscriber's, for instance). Disabled fields keep their
        # saved value whatever is posted.
        if not (acting_user and acting_user.is_senior_staff):
            self.fields['email'].disabled = True
            self.fields['email'].help_text = 'Only an Editor-in-Chief or Admin can change the login email.'


class AccountCreateForm(ModelForm):
    """Editorial creation of a login account (a contributor who hasn't
    self-registered, or an Author profile that now needs to log in).

    The password is optional. Set one here and the account works right
    away; leave both boxes empty and the account is created without a
    usable password and the person is emailed a link to choose their own
    (users/invites.py) — so an editor never has to invent and pass on a
    password. Skips the pending-verification queue: an editor creating the
    account is already vouching for it.
    """

    ROLE_CHOICES = [
        (User.Role.VERIFIED_AUTHOR, 'Verified author'),
        (User.Role.UNVERIFIED, 'Reader (unverified)'),
    ]

    role = forms.ChoiceField(choices=ROLE_CHOICES, initial=User.Role.VERIFIED_AUTHOR)
    password1 = forms.CharField(
        label='Password', required=False, strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='Optional. Leave both password boxes empty to email them a link to set their own.',
    )
    password2 = forms.CharField(
        label='Confirm password', required=False, strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'role']

    def clean(self):
        from django.contrib.auth import password_validation

        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1') or ''
        password2 = cleaned_data.get('password2') or ''
        if password1 or password2:
            if password1 != password2:
                self.add_error('password2', 'The two passwords don\'t match.')
            else:
                try:
                    password_validation.validate_password(password1, self.instance)
                except forms.ValidationError as error:
                    self.add_error('password1', error)
        return cleaned_data

    @property
    def sends_invite(self) -> bool:
        """True when no password was set — the view then emails an invite."""
        return not self.cleaned_data.get('password1')

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('password1'):
            user.set_password(self.cleaned_data['password1'])
        else:
            user.set_unusable_password()
        user.role = self.cleaned_data['role']
        if user.role == User.Role.VERIFIED_AUTHOR:
            user.is_verified = True
            user.verification_status = User.VerificationStatus.APPROVED
        if commit:
            user.save()
        return user


# Editorial staff accounts (Editor / Editor-in-Chief / Admin) — deliberately a
# smaller field set than ACCOUNT_PROFILE_FIELDS: staff don't need the
# academic-author fields (ORCID, affiliation, CV, publications, etc.), just
# who they are and what they're allowed to do.
# Same composition as User.EDITORIAL_ROLES (see users/models.py) — kept as a
# separate name here since this one means "assignable via this form", while
# EDITORIAL_ROLES means "can access editorial views"; they happen to match.
STAFF_ROLES = User.EDITORIAL_ROLES
STAFF_FIELDS = ['first_name', 'last_name', 'email', 'photo', 'role', 'is_active']


class StaffFormMixin:
    """Shared role-choice guardrail: an Editor-in-Chief managing this screen
    can grant Editor/EiC but not Admin — only an existing Admin can mint a
    new one. Requires the requesting user passed in as `acting_user`.
    """

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(v, l) for v, l in User.Role.choices if v in STAFF_ROLES]
        current_role = getattr(self.instance, 'role', None)
        # An EiC can't promote someone TO Admin, but editing an existing
        # Admin's other fields shouldn't force-demote them just because the
        # choice list wouldn't otherwise include their current role.
        if acting_user and acting_user.role != User.Role.ADMIN and current_role != User.Role.ADMIN:
            choices = [(v, l) for v, l in choices if v != User.Role.ADMIN]
        self.fields['role'].choices = choices
        # Publishing rights for Editors (EiC/Admin always have them) — see
        # User.can_publish. Applied by the view after the account is saved.
        self.fields['can_publish'] = forms.BooleanField(
            required=False, label='Can publish articles',
            help_text='Publish, schedule, update or unpublish live articles and add public corrections. '
                      'Editors-in-Chief and Admins can always publish.',
            initial=bool(self.instance.pk and self.instance.user_permissions.filter(
                codename='publish_article', content_type__app_label='articles',
            ).exists()),
        )

    def apply_publish_permission(self, user):
        """Grant/revoke articles.publish_article to match the checkbox."""
        permission = Permission.objects.get(codename='publish_article', content_type__app_label='articles')
        if self.cleaned_data.get('can_publish'):
            user.user_permissions.add(permission)
        else:
            user.user_permissions.remove(permission)


class StaffManageForm(StaffFormMixin, ModelForm):
    class Meta:
        model = User
        fields = STAFF_FIELDS


class StaffCreateForm(StaffFormMixin, UserCreationForm):
    """Editorial creation of a new staff account. Unlike author creation,
    there's no verification-queue bypass to document — staff accounts were
    never subject to it (VERIFICATION_QUEUE_ROLES doesn't include them) —
    but is_verified/verification_status are set to keep them consistent
    with what an approved account looks like everywhere else.
    """

    class Meta:
        model = User
        fields = STAFF_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['is_active'].initial = True

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_verified = True
        user.verification_status = User.VerificationStatus.APPROVED
        if commit:
            user.save()
        return user


class ChangeRoleForm(forms.Form):
    """The actual "set permissions" control — every other screen only
    manages a user within its own tier (Authors can't promote out of
    unverified/verified_author; Staff can only edit existing Editor/EiC/Admin
    accounts). This is the one place that can move a user across the whole
    Role enum, from any starting role to any other. EiC/Admin only, same
    Admin-grant guardrail as StaffFormMixin — an EiC still can't hand out Admin.
    """

    role = forms.ChoiceField(choices=User.Role.choices, label='Role')

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = list(User.Role.choices)
        if acting_user and acting_user.role != User.Role.ADMIN:
            choices = [(v, l) for v, l in choices if v != User.Role.ADMIN]
        self.fields['role'].choices = choices


# -- Django Group/Permission management -------------------------------------
# The custom-admin equivalent of /admin/auth/group/ — nothing in this
# codebase checks group membership or has_perm() yet (every view still
# gates on User.role via role_required), so this is management-only for now:
# it lets an Admin define what a group *would* grant, ahead of anything in
# the app actually consulting it. See ARCHITECTURE.md §6.2.

class GroupForm(ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'permissions']
        widgets = {
            'permissions': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['permissions'].queryset = Permission.objects.select_related(
            'content_type',
        ).order_by('content_type__app_label', 'content_type__model', 'codename')

    def permissions_by_app(self):
        """Grouped for the template — a flat checkbox list of 100+
        permissions would be unusable."""
        if self.is_bound:
            # Re-rendering after a validation error — reflect what was just
            # submitted, not the (possibly different) saved state.
            selected_ids = {int(v) for v in self.data.getlist(self.add_prefix('permissions'))}
        elif self.instance.pk:
            selected_ids = set(self.instance.permissions.values_list('pk', flat=True))
        else:
            selected_ids = set()
        groups = {}
        for perm in self.fields['permissions'].queryset:
            groups.setdefault(perm.content_type.app_label, []).append((perm, perm.pk in selected_ids))
        return sorted(groups.items())


class UserGroupsForm(forms.Form):
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.order_by('name'), required=False, widget=forms.CheckboxSelectMultiple,
        label='Groups',
    )
