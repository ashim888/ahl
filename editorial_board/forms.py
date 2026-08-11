from django import forms

from ajna_health_lens.forms import apply_tailwind_widgets
from users.models import User

from .models import EditorialBoardMember


class EditorialBoardMemberForm(forms.ModelForm):
    class Meta:
        model = EditorialBoardMember
        fields = ['name', 'role_title', 'affiliation', 'bio', 'photo', 'order', 'is_active', 'user']
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 5}),
        }
        labels = {'user': 'Linked author account'}
        help_texts = {
            'user': "Optional — if this board member also has a site account, link it to "
                    'cross-reference their board bio with their author byline page.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = User.objects.order_by('first_name', 'last_name')
        self.fields['user'].required = False
        self.fields['user'].empty_label = '— No linked account —'
        apply_tailwind_widgets(self, skip=('cv_file', 'file', 'photo', 'is_active'))
