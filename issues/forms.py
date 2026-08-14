from django import forms
from django.utils.text import slugify

from .models import Issue


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ['title', 'slug', 'cover_image', 'publication_date', 'is_published', 'editorial_note']
        widgets = {
            'publication_date': forms.DateInput(attrs={'type': 'date'}),
            'editorial_note': forms.Textarea(attrs={'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        self.fields['slug'].help_text = 'Leave blank to generate from the title.'

    def clean_slug(self):
        slug = self.cleaned_data.get('slug') or slugify(self.data.get('title', ''))
        if not slug:
            raise forms.ValidationError('Could not generate a URL slug — please enter a title.')
        conflict = Issue.objects.filter(slug=slug).exclude(pk=self.instance.pk)
        if conflict.exists():
            raise forms.ValidationError('This slug is already in use by another issue.')
        return slug
