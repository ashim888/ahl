from django import forms

from ajna_health_lens.forms import apply_tailwind_widgets

from .models import EditorialBoardMember


class EditorialBoardMemberForm(forms.ModelForm):
    class Meta:
        model = EditorialBoardMember
        fields = ['name', 'role_title', 'affiliation', 'bio', 'photo', 'order', 'is_active']
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind_widgets(self, skip=('cv_file', 'file', 'photo', 'is_active'))
