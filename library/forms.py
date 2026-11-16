import json

from django import forms

from articles.forms import TagifyKeywordsField, TagifyRelatedArticlesField

from .models import Resource


class ResourceForm(forms.ModelForm):
    """Editor form for a library resource. Topics and related articles use the
    same Tagify fields as the article form (articles/forms.py), so a topic
    typed here is the same Keyword the article pages use."""

    keywords = TagifyKeywordsField(
        required=False, label='Topics',
        help_text='Press enter after each one. Existing topics are suggested as you type.',
    )
    related = TagifyRelatedArticlesField(
        required=False, label='Related articles',
        help_text='Our published articles about this resource, if any. Shown on both pages.',
    )

    class Meta:
        model = Resource
        fields = ['title', 'resource_type', 'summary', 'source', 'year', 'language',
                  'file', 'external_url', 'is_published']
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 4}),
            'year': forms.NumberInput(attrs={'min': 1900, 'max': 2100}),
        }
        labels = {'is_published': 'Published (visible in the library)', 'external_url': 'Link'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['keywords'].initial = json.dumps(
                [{'value': k.name} for k in self.instance.keyword_tags.all()], ensure_ascii=False)
            self.fields['related'].initial = json.dumps(
                [{'value': a.title, 'id': a.pk} for a in self.instance.related_articles.all()], ensure_ascii=False)

    def clean_year(self):
        year = self.cleaned_data.get('year')
        if year and not 1900 <= year <= 2100:
            raise forms.ValidationError('Enter the year in AD, e.g. 2024.')
        return year

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            self._save_relations(instance)
        else:
            original = self.save_m2m

            def save_m2m():
                original()
                self._save_relations(instance)
            self.save_m2m = save_m2m
        return instance

    def _save_relations(self, instance):
        instance.keyword_tags.set(self.cleaned_data.get('keywords', []))
        instance.related_articles.set(self.cleaned_data.get('related', []))
