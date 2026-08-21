from django import forms

from .models import StoryPitch


class StoryPitchForm(forms.ModelForm):
    """Public submit form (verified authors only — see views.py). Includes
    a honeypot as a first line of spam defense, same pattern as
    newsletter/forms.py:SubscribeForm — not full mitigation on its own, the
    view also rate-limits and the form is already login-gated.
    """

    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = StoryPitch
        fields = ['title', 'summary', 'body']
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 5}),
            'body': forms.Textarea(attrs={'rows': 10}),
        }

    def clean_website(self):
        value = self.cleaned_data.get('website')
        if value:
            raise forms.ValidationError('Spam detected.')
        return value


class PitchDecisionForm(forms.ModelForm):
    class Meta:
        model = StoryPitch
        fields = ['editor_feedback']
        widgets = {
            'editor_feedback': forms.Textarea(attrs={'rows': 4}),
        }
