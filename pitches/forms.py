from django import forms

from .captcha import verify_turnstile
from .models import StoryPitch


class StoryPitchForm(forms.ModelForm):
    """Public submit form — fully open, no login required (August 2026;
    previously verified-author-only, then any-authenticated-account-only).
    Anyone can pitch a story; a logged-out visitor's name/email are
    collected directly on the pitch (submitter_name/submitter_email) since
    there's no account to pull them from — that's also how the editorial
    team can actually follow up with (or credit) someone who never
    registered. This openness is exactly why the form now carries real
    CAPTCHA (Cloudflare Turnstile, see clean() below) on top of the
    pre-existing honeypot (same pattern as newsletter/forms.py:SubscribeForm)
    and the view's per-IP rate limit.
    """

    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = StoryPitch
        fields = ['title', 'summary', 'body', 'submitter_name', 'submitter_email']
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 5}),
            'body': forms.Textarea(attrs={'rows': 10}),
        }
        labels = {
            'submitter_name': 'Your name',
            'submitter_email': 'Your email',
        }

    def __init__(self, *args, request=None, **kwargs):
        # Needed for two things: is this visitor logged in (do we still need
        # to ask for contact info at all?), and the Turnstile check below
        # (the token verification call wants the visitor's IP). Neither is a
        # model field, so it's taken as a plain kwarg rather than something
        # Meta.fields could carry.
        self.request = request
        super().__init__(*args, **kwargs)
        if request and request.user.is_authenticated:
            # Already have their identity from the account — don't ask again.
            del self.fields['submitter_name']
            del self.fields['submitter_email']
        else:
            self.fields['submitter_name'].required = True
            self.fields['submitter_email'].required = True
            self.fields['submitter_email'].help_text = "So we can follow up if we'd like to run your story."

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
