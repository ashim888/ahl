from django import forms
from django_ckeditor_5.widgets import CKEditor5Widget

from articles.sanitize import sanitize_editorial_html

from .models import NewsletterIssue


class SubscribeForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'placeholder': 'you@example.com'}),
    )
    # Honeypot — real visitors never see or fill this (hidden via CSS in the
    # template); a bot filling every field trips it. Not full spam
    # mitigation (see ROADMAP.md Phase 9), but a free first line of defense
    # on a public, unauthenticated POST endpoint.
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_website(self):
        value = self.cleaned_data.get('website')
        if value:
            raise forms.ValidationError('Spam detected.')
        return value


class NewsletterIssueForm(forms.ModelForm):
    class Meta:
        model = NewsletterIssue
        fields = ['subject', 'body_html']
        widgets = {
            # Same "trusted, editor-authored HTML" pattern as
            # Article.html_content (see NewsletterIssue's docstring) — same
            # 'articles' CKEDITOR_5_CONFIGS entry, including sourceEditing
            # for editors who need to drop into raw HTML.
            'body_html': CKEditor5Widget(config_name='articles'),
        }

    def clean_body_html(self):
        # See articles/sanitize.py — same "trusted, editor-authored HTML"
        # field, same defense-in-depth treatment as Article.html_content.
        return sanitize_editorial_html(self.cleaned_data.get('body_html'))
