from django import forms

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
            'body_html': forms.Textarea(attrs={'rows': 16, 'class': 'font-mono text-xs'}),
        }
