from django.contrib.auth.forms import UserCreationForm
from django.forms import ModelForm

from .models import User

TAILWIND_INPUT = 'w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900'


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
        for name, field in self.fields.items():
            if name == 'cv_file':
                continue
            css = TAILWIND_INPUT
            field.widget.attrs['class'] = css


class ProfileUpdateForm(ModelForm):
    """Editable profile fields. Deliberately excludes email/role/verification_status —
    those are admin-controlled, not self-service.
    """

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name',
            'orcid', 'affiliation', 'department', 'bio', 'cv_file',
            'research_interests', 'linkedin_url', 'researchgate_url', 'publications',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'cv_file':
                continue
            field.widget.attrs['class'] = TAILWIND_INPUT
