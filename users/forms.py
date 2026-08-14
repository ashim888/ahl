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
