from django import forms
from django.urls import NoReverseMatch, reverse

from .models import Section

# Feature pages a top-level menu entry can point to (Section.link_url_name).
# A dropdown, not free text: the menu renders on every page, so a mistyped
# route name would break the whole site.
LINK_TARGETS = [
    ('', '— None: a normal content section —'),
    ('library:resource_list', 'Health Library'),
    ('articles:fact_check_list', 'Fact checks'),
    ('training:course_list', 'Training'),
    ('issues:issue_list', 'Issues'),
    ('articles:video_list', 'Videos'),
    ('articles:topic_list', 'Topics'),
]


class SectionForm(forms.ModelForm):
    """django-modeltranslation adds real name_en/name_ne columns behind the
    scenes (see sections/translation.py) — a plain ModelForm needs those
    listed explicitly, unlike Django admin (which gets them automatically
    via modeltranslation's admin integration, not used here since every
    editorial screen in this project is a custom /manage/ view, not admin).
    """

    class Meta:
        model = Section
        fields = ['name_en', 'name_ne', 'slug', 'parent', 'order', 'is_active', 'link_url_name']
        labels = {
            'name_en': 'Name (English)',
            'name_ne': 'Name (Nepali)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only top-level sections are valid parents — Section.clean() already
        # enforces the two-level limit, but narrowing the queryset here means
        # an editor can't even pick an invalid parent from the dropdown.
        queryset = Section.objects.filter(parent__isnull=True)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        self.fields['parent'].queryset = queryset
        self.fields['parent'].required = False
        self.fields['parent'].empty_label = '— Top-level —'
        choices = list(LINK_TARGETS)
        current = self.instance.link_url_name
        if current and current not in dict(choices):
            choices.append((current, current))  # keep an existing value editable
        self.fields['link_url_name'] = forms.ChoiceField(
            choices=choices, required=False, label='Link to a feature page',
            help_text='Only for a top-level entry that should open a feature page (e.g. the Health Library) '
                      'instead of a section landing page.',
        )

    def clean_link_url_name(self):
        value = self.cleaned_data.get('link_url_name', '')
        if value:
            try:
                reverse(value)
            except NoReverseMatch:
                raise forms.ValidationError('That page no longer exists. Pick another one.')
        return value

    # No custom clean() needed — ModelForm._post_clean() already calls
    # Section.clean() via full_clean(), so the two-level/link-override
    # validation on the model surfaces as a normal form error automatically.
