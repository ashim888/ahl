from django import forms
from django_ckeditor_5.widgets import CKEditor5Widget

from .models import SitePage


class SitePageForm(forms.ModelForm):
    class Meta:
        model = SitePage
        fields = ['title_en', 'body_en', 'title_ne', 'body_ne', 'is_published']
        labels = {
            'title_en': 'Title', 'body_en': 'Text',
            'title_ne': 'Title (Nepali)', 'body_ne': 'Text (Nepali)',
        }
        help_texts = {'title_ne': 'Optional — readers on the Nepali site see the English page until this is filled in.'}
        widgets = {
            'body_en': CKEditor5Widget(config_name='default'),
            'body_ne': CKEditor5Widget(config_name='default'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title_en'].required = True
