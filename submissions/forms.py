from django import forms

from ajna_health_lens.forms import apply_tailwind_widgets
from articles.models import Article

from .validators import manuscript_extension_validator, validate_manuscript_file_size


class SubmissionFormStep1(forms.Form):
    """Metadata — including the author declarations from ARCHITECTURE.md's
    Submission schema (cover letter, suggested reviewers, conflict of interest).
    """

    title = forms.CharField(max_length=500)
    article_type = forms.ChoiceField(choices=Article.ArticleType.choices)
    abstract = forms.CharField(widget=forms.Textarea(attrs={'rows': 6}))
    keywords = forms.CharField(max_length=500, required=False)
    cover_letter = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}), required=False)
    suggested_reviewers = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    conflict_of_interest = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind_widgets(self)


class SubmissionFormStep2(forms.Form):
    file = forms.FileField(
        validators=[manuscript_extension_validator, validate_manuscript_file_size],
        help_text='PDF, DOC, or DOCX, up to 50 MB.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind_widgets(self)


class SubmissionFormStep3(forms.Form):
    confirm = forms.BooleanField(
        label='I confirm this submission is accurate, complete, and ready for editorial screening.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind_widgets(self, skip=('confirm',))


class RevisionUploadForm(forms.Form):
    file = forms.FileField(
        validators=[manuscript_extension_validator, validate_manuscript_file_size],
        help_text='PDF, DOC, or DOCX, up to 50 MB.',
    )
