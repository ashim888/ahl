from django import forms

from .models import Issue


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ['volume', 'number', 'title', 'cover_image', 'publication_date', 'is_published', 'editorial_note']
        widgets = {
            'publication_date': forms.DateInput(attrs={'type': 'date'}),
            'editorial_note': forms.Textarea(attrs={'rows': 5}),
        }
