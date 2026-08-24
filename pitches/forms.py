from django import forms

from .captcha import verify_turnstile
from .models import StoryPitch


class StoryPitchForm(forms.ModelForm):
    """Public submit form — open to any authenticated account (August 2026;
    previously verified-author-only). That widening is exactly why this now
    also carries real CAPTCHA (Cloudflare Turnstile, see clean() below) on
    top of the pre-existing honeypot (same pattern as
    newsletter/forms.py:SubscribeForm) and the view's rate limit — a
    login-gate alone was a much stronger bot deterrent when only vetted
    verified_author accounts could reach this form.
    """

    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = StoryPitch
        fields = ['title', 'summary', 'body']
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 5}),
            'body': forms.Textarea(attrs={'rows': 10}),
        }

    def __init__(self, *args, request=None, **kwargs):
        # Needed only for the Turnstile check below (the token verification
        # call wants the visitor's IP) — not a model field, so it's taken as
        # a plain kwarg rather than something Meta.fields could carry.
        self.request = request
        super().__init__(*args, **kwargs)

    def clean_website(self):
        value = self.cleaned_data.get('website')
        if value:
            raise forms.ValidationError('Spam detected.')
        return value

    def clean(self):
        cleaned_data = super().clean()
        token = self.data.get('cf-turnstile-response', '')
        remote_ip = self.request.META.get('REMOTE_ADDR') if self.request else None
        if not verify_turnstile(token, remote_ip):
            raise forms.ValidationError('CAPTCHA verification failed — please try again.')
        return cleaned_data


class PitchDecisionForm(forms.ModelForm):
    class Meta:
        model = StoryPitch
        fields = ['editor_feedback']
        widgets = {
            'editor_feedback': forms.Textarea(attrs={'rows': 4}),
        }
