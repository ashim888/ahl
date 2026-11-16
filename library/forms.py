import json

from django import forms
from django.db.models import Q

from articles.forms import TagifyKeywordsField, TagifyRelatedArticlesField

from .models import GlossaryTerm, Resource


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


class GlossaryTermForm(forms.ModelForm):
    keywords = TagifyKeywordsField(
        required=False, label='Topics',
        help_text='Press enter after each one. Existing topics are suggested as you type.',
    )

    class Meta:
        model = GlossaryTerm
        fields = ['term_ne', 'term_en', 'also_called', 'definition_ne', 'definition_en', 'related_terms',
                  'is_published']
        widgets = {
            'definition_ne': forms.Textarea(attrs={'rows': 3}),
            'definition_en': forms.Textarea(attrs={'rows': 3}),
            'related_terms': forms.SelectMultiple(attrs={'size': 8}),
        }
        labels = {'is_published': 'Published (visible in the glossary)'}
        help_texts = {'related_terms': 'Hold Ctrl (⌘ on Mac) to pick several.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        others = GlossaryTerm.objects.all()
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
            self.fields['keywords'].initial = json.dumps(
                [{'value': k.name} for k in self.instance.keyword_tags.all()], ensure_ascii=False)
        self.fields['related_terms'].queryset = others
        self.fields['related_terms'].required = False

    def clean(self):
        cleaned = super().clean()
        names = [cleaned.get('term_ne', '').strip(), cleaned.get('term_en', '').strip()]
        for name in filter(None, names):
            clash = GlossaryTerm.objects.filter(Q(term_ne__iexact=name) | Q(term_en__iexact=name))
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise forms.ValidationError(f'"{name}" is already in the glossary.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            instance.keyword_tags.set(self.cleaned_data.get('keywords', []))
        return instance
