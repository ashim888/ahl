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
            'orcid', 'affiliation', 'department', 'bio', 'cv_file',
            'research_interests', 'linkedin_url', 'researchgate_url', 'publications',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind_widgets(self)
