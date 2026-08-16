from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.forms import ModelForm

from ajna_health_lens.forms import apply_tailwind_widgets
from .models import User


class RegistrationForm(UserCreationForm):
    """Self-registration. Always creates role=unverified, verification_status=pending
    (the model defaults already do this) — verification is a manual editorial step.
    """

    class Meta:
        model = User
        fields = [
            'email', 'first_name', 'last_name',
            'orcid', 'affiliation', 'department', 'bio', 'cv_file',
            'research_interests', 'linkedin_url', 'researchgate_url', 'publications',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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


# Fields shared by the editorial "manage authors" create/update forms below.
# Deliberately excludes role/verification_status/is_verified — those stay
# owned by the verification queue (users/views.py verification_decide) so
# there's one place that keeps them in sync, not two flows that can drift.
AUTHOR_PROFILE_FIELDS = [
    'first_name', 'last_name', 'email',
    'orcid', 'affiliation', 'department', 'bio', 'photo', 'cv_file',
    'research_interests', 'linkedin_url', 'researchgate_url', 'publications',
    'is_active',
]


class AuthorManageForm(ModelForm):
    """Editorial edit of an existing author's profile — content fields plus
    is_active as a reversible deactivate/reactivate toggle (not a hard
    delete of the account or their authorship history).
    """

    class Meta:
        model = User
        fields = AUTHOR_PROFILE_FIELDS


class AuthorCreateForm(UserCreationForm):
    """Editorial creation of a new author account (e.g. a contributor who
    hasn't self-registered). Skips the pending-verification queue — an
    editor creating the account directly is already vouching for it — so
    the account is created as an approved Verified Author, not Unverified.
    """

    class Meta:
        model = User
        fields = AUTHOR_PROFILE_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['is_active'].initial = True

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.VERIFIED_AUTHOR
        user.is_verified = True
        user.verification_status = User.VerificationStatus.APPROVED
        if commit:
            user.save()
        return user


# Editorial staff accounts (Editor / Editor-in-Chief / Admin) — deliberately a
# smaller field set than AUTHOR_PROFILE_FIELDS: staff don't need the
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
