from django import forms

from .models import Section


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
            'link_url_name': 'Link override',
        }
        help_texts = {
            'link_url_name': Section._meta.get_field('link_url_name').help_text,
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

    # No custom clean() needed — ModelForm._post_clean() already calls
    # Section.clean() via full_clean(), so the two-level/link-override
    # validation on the model surfaces as a normal form error automatically.
