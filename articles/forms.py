from django import forms

from .models import Article


class ArticleForm(forms.ModelForm):
    """Front-end editorial CRUD form. Authors (the Article<->User through model,
    with ordering/corresponding-author flags) are deliberately still managed via
    the Django admin's inline — a plain multi-select here can't represent that
    ordering cleanly, so this form sticks to the article's own fields.
    """

    class Meta:
        model = Article
        fields = [
            'title', 'slug', 'article_type', 'access_type', 'status', 'is_pinned',
            'abstract', 'keywords', 'issue', 'volume', 'page_numbers', 'doi',
            'submission_date', 'acceptance_date', 'publication_date',
            'html_content', 'references', 'featured_image', 'pdf_file',
        ]
        widgets = {
            'submission_date': forms.DateInput(attrs={'type': 'date'}),
            'acceptance_date': forms.DateInput(attrs={'type': 'date'}),
            'publication_date': forms.DateInput(attrs={'type': 'date'}),
            'abstract': forms.Textarea(attrs={'rows': 5}),
            'html_content': forms.Textarea(attrs={'rows': 16, 'class': 'font-mono text-xs'}),
            'references': forms.Textarea(attrs={'rows': 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['access_type'].required = False
        # access_type is a plain CharField+choices (not a FK), so the blank
        # option's label is set by overriding choices, not via empty_label.
        self.fields['access_type'].choices = [('', 'Default from article type')] + list(Article.AccessType.choices)
